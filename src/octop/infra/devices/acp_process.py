"""Volatile ACP stdio processes on an explicitly opted-in device.

No account token, manager environment or ACP output is written to device state.
The authenticated device connection owns these processes and closes them on loss
of the connection or a grant change.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import os
import shutil
import signal
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from octop.infra.devices.process_scope import WindowsJob


class ACPProcessError(ValueError):
    """Invalid or unavailable local ACP process."""


@dataclass
class _Process:
    process: asyncio.subprocess.Process
    output: asyncio.Queue[bytes | None]
    reader: asyncio.Task[None]
    stderr: asyncio.Task[None]
    job: Any = None


class DeviceACPProcesses:
    def __init__(self) -> None:
        self._sessions: dict[str, _Process] = {}

    @staticmethod
    def process_environment() -> dict[str, str]:
        environment = dict(os.environ)
        if os.name == "nt":
            from urllib.request import getproxies

            for scheme, address in getproxies().items():
                if scheme in {"http", "https"}:
                    key = scheme.upper() + "_PROXY"
                    if not any(name.upper() == key for name in environment):
                        environment[key] = address
            environment.setdefault("NO_PROXY", "localhost,127.0.0.1")
        return environment

    @staticmethod
    def check(command: str, args: list[str]) -> dict[str, Any]:
        executable = shutil.which(command) if command and "\x00" not in command else None
        return {
            "available": executable is not None,
            "executable": executable,
            "code": "ACP_EXECUTABLE_FOUND" if executable else "ACP_EXECUTABLE_NOT_FOUND",
            "authentication": "not_checked",
            "adapter": "download_may_be_required"
            if Path(command).stem.lower() in {"npx", "npm"}
            else "not_checked",
        }

    async def open(self, command: str, args: list[str], cwd: Path) -> dict[str, str]:
        if (
            not isinstance(command, str)
            or not command
            or "\x00" in command
            or len(command) > 1024
            or not isinstance(args, list)
            or len(args) > 64
            or any(not isinstance(arg, str) or "\x00" in arg or len(arg) > 4096 for arg in args)
        ):
            raise ACPProcessError("invalid ACP runner command")
        if len(self._sessions) >= 4:
            raise ACPProcessError("too many ACP sessions on device")
        from octop.infra.devices.executor import _reject_links

        _reject_links(cwd)
        if not cwd.is_dir():
            raise ACPProcessError("ACP working directory unavailable")
        executable = shutil.which(command)
        if executable is None:
            raise ACPProcessError(
                "ACP_EXECUTABLE_NOT_FOUND: configure the runner path on this device"
            )
        # Launch npm's JS entry directly. Batch shims otherwise depend on cmd.exe
        # quoting, shell settings and PATH inherited by a long-running client.
        if os.name == "nt" and Path(executable).name.lower() in {"npx.cmd", "npm.cmd"}:
            folder = Path(executable).parent
            script = folder / "node_modules" / "npm" / "bin" / (Path(executable).stem + "-cli.js")
            node = folder / "node.exe"
            if script.is_file() and node.is_file():
                executable, args = str(node), [str(script), *args]
        spawn: dict[str, Any] = {
            "cwd": cwd,
            "stdin": asyncio.subprocess.PIPE,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "env": self.process_environment(),
        }
        if os.name == "nt":
            spawn["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW | 0x4  # type: ignore[attr-defined, unused-ignore]
            )
        else:
            spawn["start_new_session"] = True
        launch = asyncio.create_task(asyncio.create_subprocess_exec(executable, *args, **spawn))
        try:
            process = await asyncio.shield(launch)
        except asyncio.CancelledError:
            process = await launch
            if os.name != "nt":
                with contextlib.suppress(ProcessLookupError):
                    getattr(os, "killpg")(process.pid, getattr(signal, "SIGKILL"))  # noqa: B009 - POSIX only
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            raise
        except OSError as exc:
            raise ACPProcessError(
                "ACP_START_FAILED: device could not launch the configured executable"
            ) from exc
        job = None
        try:
            if os.name == "nt":
                job = WindowsJob(process.pid)
            stdout, stderr = process.stdout, process.stderr
            assert stdout is not None and stderr is not None
            output: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=32)

            async def read_output() -> None:
                try:
                    while chunk := await stdout.read(65536):
                        await output.put(chunk)
                finally:
                    await output.put(None)

            async def drain_stderr() -> None:
                while await stderr.read(65536):
                    pass

            session_id = uuid.uuid4().hex
            self._sessions[session_id] = _Process(
                process,
                output,
                asyncio.create_task(read_output()),
                asyncio.create_task(drain_stderr()),
                job,
            )
            return {"session_id": session_id, "cwd": str(cwd)}
        except BaseException:
            if job is not None:
                job.close()
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            raise

    def _get(self, session_id: str) -> _Process:
        session = self._sessions.get(session_id)
        if session is None:
            raise ACPProcessError("ACP session unavailable")
        return session

    async def write(self, session_id: str, encoded: str) -> dict[str, int]:
        session = self._get(session_id)
        if not isinstance(encoded, str):
            raise ACPProcessError("invalid ACP input")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ACPProcessError("invalid ACP input") from exc
        if not data or len(data) > 131072:
            raise ACPProcessError("ACP input must be 1–131072 bytes")
        if session.process.returncode is not None or session.process.stdin is None:
            raise ACPProcessError("ACP process exited")
        try:
            session.process.stdin.write(data)
            await session.process.stdin.drain()
        except (OSError, ConnectionError) as exc:
            raise ACPProcessError("ACP process disconnected") from exc
        return {"bytes_written": len(data)}

    async def poll(self, session_id: str) -> dict[str, Any]:
        session = self._get(session_id)
        try:
            chunk = await asyncio.wait_for(session.output.get(), timeout=20)
        except TimeoutError:
            chunk = b""
        if chunk is None:
            return {"data_b64": "", "eof": True}
        return {"data_b64": base64.b64encode(chunk).decode("ascii"), "eof": False}

    async def close(self, session_id: str) -> dict[str, bool]:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return {"closed": False}
        if session.job is not None:
            session.job.close()
        elif os.name != "nt" and session.process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                getattr(os, "killpg")(session.process.pid, getattr(signal, "SIGKILL"))  # noqa: B009 - POSIX only
        if session.process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                session.process.kill()
        await session.process.wait()
        for task in (session.reader, session.stderr):
            task.cancel()
        await asyncio.gather(session.reader, session.stderr, return_exceptions=True)
        if session.process.stdin is not None:
            session.process.stdin.close()
        return {"closed": True}

    async def close_all(self) -> None:
        for session_id in list(self._sessions):
            await self.close(session_id)
