"""Context-bound native terminal sessions with bounded, sequenced scrollback."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from octop.infra.devices.jobs import process_identity, stop_process_tree

SCROLLBACK = 256 * 1024


def supported() -> bool:
    return importlib.util.find_spec("winpty" if os.name == "nt" else "ptyprocess") is not None


@dataclass
class TerminalSession:
    process: asyncio.subprocess.Process
    context_id: str
    cwd: str
    reader: asyncio.Task[None] | None = None
    output: bytearray = field(default_factory=bytearray)
    offset: int = 0
    last_access: float = field(default_factory=time.monotonic)
    identity: dict[str, Any] | None = None
    returncode: int | None = None
    error: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class DeviceTerminals:
    def __init__(self) -> None:
        self.sessions: dict[str, TerminalSession] = {}
        self._open_lock = asyncio.Lock()
        self._reaper: asyncio.Task[None] | None = None

    @staticmethod
    def dimensions(params: dict[str, Any]) -> tuple[int, int]:
        cols, rows = params.get("cols", 80), params.get("rows", 24)
        if (
            type(cols) is not int
            or type(rows) is not int
            or not 2 <= cols <= 500
            or not 2 <= rows <= 200
        ):
            raise ValueError("invalid terminal dimensions")
        return cols, rows

    def _get(self, params: dict[str, Any]) -> TerminalSession:
        session = self.sessions.get(str(params.get("session_id") or ""))
        if session is None or session.context_id != params.get("execution_context_id"):
            raise ValueError("terminal session unavailable for this execution context")
        session.last_access = time.monotonic()
        return session

    async def _send(self, session: TerminalSession, frame: dict[str, Any]) -> None:
        if session.process.returncode is not None or session.process.stdin is None:
            raise ValueError("terminal process has exited")
        async with session.lock:
            session.process.stdin.write((json.dumps(frame) + "\n").encode())
            await session.process.stdin.drain()

    async def call(self, action: str, params: dict[str, Any], cwd: Path) -> dict[str, Any]:
        if action == "terminal.open":
            async with self._open_lock:
                return await self._open(params, cwd)
        session = self._get(params)
        if action == "terminal.poll":
            offset = params.get("offset", 0)
            if (
                type(offset) is not int
                or offset < 0
                or offset > session.offset + len(session.output)
            ):
                raise ValueError("invalid terminal output offset")
            start = max(offset, session.offset)
            data = bytes(session.output[start - session.offset : start - session.offset + 32768])
            return {
                "data_b64": base64.b64encode(data).decode(),
                "offset": start,
                "next_offset": start + len(data),
                "gap": offset < session.offset,
                "eof": session.process.returncode is not None
                and session.reader is not None
                and session.reader.done()
                and start + len(data) >= session.offset + len(session.output),
                "returncode": session.returncode,
                "error": session.error,
            }
        if action == "terminal.input":
            value = params.get("data_b64")
            if not isinstance(value, str) or len(value) > 12000:
                raise ValueError("invalid terminal input")
            data = base64.b64decode(value, validate=True)
            if len(data) > 8192:
                raise ValueError("terminal input too large")
            data.decode("utf-8")
            await self._send(session, {"type": "input", "data_b64": value})
            return {"accepted_bytes": len(data)}
        if action == "terminal.resize":
            cols, rows = self.dimensions(params)
            await self._send(session, {"type": "resize", "cols": cols, "rows": rows})
            return {"cols": cols, "rows": rows}
        if action == "terminal.close":
            await self._close(str(params["session_id"]), session)
            return {"closed": True}
        raise ValueError("unsupported terminal action")

    async def _open(self, params: dict[str, Any], cwd: Path) -> dict[str, Any]:
        session_id = str(params.get("session_id") or "")
        context_id = params.get("execution_context_id")
        if (
            not re.fullmatch(r"[a-zA-Z0-9-]{1,100}", session_id)
            or not isinstance(context_id, str)
            or not context_id
        ):
            raise ValueError("terminal requires session and execution context IDs")
        if session_id in self.sessions:
            session = self._get(params)
            if session.cwd != str(cwd):
                raise ValueError("terminal working directory changed")
            return {
                "session_id": session_id,
                "cwd": session.cwd,
                "resumed": True,
                "exited": session.process.returncode is not None,
            }
        for key, session in list(self.sessions.items()):
            if time.monotonic() - session.last_access > 300:
                await self._close(key, session)
        if len(self.sessions) >= 8:
            raise ValueError("terminal session capacity reached")
        if not supported():
            raise ValueError("native terminal dependency unavailable on device")
        cols, rows = self.dimensions(params)
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(Path(__file__).resolve().parents[3]), *filter(None, [env.get("PYTHONPATH")])]
        )
        executable = Path(sys.executable)
        spawn: dict[str, Any] = {}
        if os.name == "nt":
            executable = executable.with_name("python.exe")
            spawn["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined, unused-ignore]
        env["PYTHONUTF8"] = "1"
        process = await asyncio.create_subprocess_exec(
            str(executable),
            "-m",
            "octop.infra.devices.terminal_worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
            **spawn,
        )
        session = TerminalSession(process, context_id, str(cwd))
        self.sessions[session_id] = session
        ready: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()

        async def read() -> None:
            assert process.stdout is not None
            try:
                while raw := await process.stdout.readline():
                    frame = json.loads(raw)
                    if frame["type"] == "ready":
                        session.identity = process_identity(frame["pid"])
                        if not ready.done():
                            ready.set_result(frame)
                    elif frame["type"] == "output":
                        session.output.extend(base64.b64decode(frame["data_b64"], validate=True))
                        excess = max(0, len(session.output) - SCROLLBACK)
                        if excess:
                            del session.output[:excess]
                            session.offset += excess
                    elif frame["type"] == "error":
                        session.error = str(frame["message"])[:500]
                    elif frame["type"] == "exit":
                        session.returncode = frame.get("code")
            finally:
                await process.wait()
                if not ready.done():
                    ready.set_exception(
                        ValueError(session.error or "terminal launch ended without receipt")
                    )

        session.reader = asyncio.create_task(read())
        try:
            await self._send(session, {"cwd": str(cwd), "cols": cols, "rows": rows})
            receipt = await asyncio.wait_for(ready, 15)
            if self._reaper is None or self._reaper.done():
                self._reaper = asyncio.create_task(self._reap_idle())
            return {
                "session_id": session_id,
                "cwd": str(cwd),
                "backend": receipt["backend"],
                "resumed": False,
            }
        except BaseException:
            await self._close(session_id, session)
            raise

    async def _close(self, session_id: str, session: TerminalSession) -> None:
        if session.process.returncode is None:
            if session.identity:
                await asyncio.to_thread(stop_process_tree, session.identity)
            with contextlib.suppress(OSError, ValueError):
                await self._send(session, {"type": "close"})
            try:
                await asyncio.wait_for(session.process.wait(), 3)
            except TimeoutError:
                if session.identity:
                    await asyncio.to_thread(stop_process_tree, session.identity)
                session.process.kill()
                await session.process.wait()
        if session.reader:
            await asyncio.gather(session.reader, return_exceptions=True)
        self.sessions.pop(session_id, None)

    async def close_all(self) -> None:
        if self._reaper:
            self._reaper.cancel()
            await asyncio.gather(self._reaper, return_exceptions=True)
        for key, session in list(self.sessions.items()):
            await self._close(key, session)

    async def _reap_idle(self) -> None:
        while self.sessions:
            await asyncio.sleep(10)
            for key, session in list(self.sessions.items()):
                if time.monotonic() - session.last_access > 300:
                    await self._close(key, session)
