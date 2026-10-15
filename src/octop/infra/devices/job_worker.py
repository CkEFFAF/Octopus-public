"""Standalone Job worker; controller/socket/browser shutdown cannot close it."""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psutil

from octop.infra.devices.jobs import (
    LOG_LIMIT,
    process_identity,
    read_state,
    write_state,
)
from octop.infra.devices.process_scope import PosixSession, ProcessScopeError, WindowsJob


async def run(path: Path) -> None:
    # An additional worker with the same manifest cannot launch a second command.
    try:
        with (path / "worker.claim").open("x"):
            pass
    except FileExistsError:
        return
    manifest = read_state(path / "job.json")
    state: dict[str, Any] = {
        "status": "queued",
        "worker": process_identity(os.getpid()),
        "updated_at": time.time(),
        "log_bytes": 0,
    }
    write_state(path / "state.json", state)
    if (path / "cancel.request").exists():
        write_state(path / "state.json", {**state, "status": "cancelled"})
        return
    spawn: dict[str, Any] = {
        "cwd": manifest["cwd"],
        "stdin": asyncio.subprocess.DEVNULL,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.STDOUT,
    }
    if os.name == "nt":
        spawn["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined, unused-ignore]
            | subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined, unused-ignore]
            | 0x4
        )
    else:
        spawn["start_new_session"] = True
    try:
        process = await asyncio.create_subprocess_exec(*manifest["argv"], **spawn)
    except OSError as exc:
        write_state(
            path / "state.json",
            {
                **state,
                "status": "failed",
                "reason": f"OS launch error: {exc}",
                "updated_at": time.time(),
            },
        )
        return
    try:
        scope = WindowsJob(process.pid) if os.name == "nt" else PosixSession(process.pid)
    except ProcessScopeError as exc:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.communicate()
        write_state(
            path / "state.json",
            {**state, "status": "failed", "reason": str(exc), "updated_at": time.time()},
        )
        return
    state.update(status="running", process=process_identity(process.pid), started_at=time.time())
    write_state(path / "state.json", state)
    assert process.stdout is not None
    stdout = process.stdout

    async def drain() -> None:
        with (path / "output.log").open("ab", buffering=0) as stream:
            while data := await stdout.read(64 * 1024):
                retained = data[: max(0, LOG_LIMIT - state["log_bytes"])]
                stream.write(retained)
                state["log_bytes"] += len(retained)
                if len(retained) != len(data):
                    state["log_truncated"] = True

    output = asyncio.create_task(drain())
    cancelled = False
    try:
        while True:
            pids = scope.pids()
            state["members"] = [
                identity for pid in pids[:256] if (identity := process_identity(pid)) is not None
            ]
            state["member_count"] = len(pids)
            state["parent_returncode"] = process.returncode
            if (path / "cancel.request").exists():
                cancelled = True
                processes = []
                for pid in pids:
                    with contextlib.suppress(psutil.NoSuchProcess):
                        processes.append(psutil.Process(pid))
                if isinstance(scope, WindowsJob):
                    scope.close()
                else:
                    for child in reversed(processes):
                        with contextlib.suppress(psutil.Error):
                            child.terminate()
                _, alive = await asyncio.to_thread(psutil.wait_procs, processes, timeout=5)
                for child in alive:
                    with contextlib.suppress(psutil.Error):
                        child.kill()
                _, alive = await asyncio.to_thread(psutil.wait_procs, alive, timeout=2)
                if alive or scope.pids():
                    state["cancel_incomplete"] = True
                break
            if process.returncode is not None and not pids:
                break
            if time.time() - state["updated_at"] >= 1:
                state["updated_at"] = time.time()
                write_state(path / "state.json", state)
            await asyncio.sleep(0.2)
        # Completion requires both an empty process scope and drained output.
        await asyncio.wait_for(output, 2)
        await asyncio.wait_for(process.wait(), 2)
    except (TimeoutError, OSError, psutil.Error, ProcessScopeError) as exc:
        state["result_incomplete"] = True
        state["reason"] = f"Job process scope or output receipt unavailable: {type(exc).__name__}"
        output.cancel()
    finally:
        scope.close()
    state.update(
        status="unknown"
        if state.get("cancel_incomplete") or state.get("result_incomplete")
        else "cancelled"
        if cancelled
        else "completed"
        if process.returncode == 0
        else "failed",
        returncode=process.returncode,
        finished_at=time.time(),
        updated_at=time.time(),
    )
    write_state(path / "state.json", state)


if __name__ == "__main__":
    asyncio.run(run(Path(sys.argv[1])))
