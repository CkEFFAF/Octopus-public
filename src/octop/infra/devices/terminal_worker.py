"""Single-purpose PTY helper; spawn the POSIX PTY before starting any threads."""

from __future__ import annotations

import base64
import contextlib
import json
import os
import shutil
import sys
import threading
from typing import Any


def run() -> None:
    settings = json.loads(sys.stdin.buffer.readline(16384))
    env = dict(os.environ, TERM="xterm-256color")
    rows, cols = settings["rows"], settings["cols"]
    if os.name == "nt":
        from winpty import PtyProcess
        from winpty.enums import Backend

        shell = (
            shutil.which("pwsh.exe")
            or shutil.which("powershell.exe")
            or os.environ.get("COMSPEC", "cmd.exe")
        )
        argv = (
            [shell, "-NoLogo", "-NoProfile"]
            if "powershell" in shell.lower() or "pwsh" in shell.lower()
            else [shell]
        )
        process: Any = PtyProcess.spawn(
            argv, cwd=settings["cwd"], env=env, dimensions=(rows, cols), backend=Backend.ConPTY
        )
    else:
        from ptyprocess import PtyProcess

        shell = os.environ.get("SHELL") or shutil.which("bash") or "/bin/sh"
        process = PtyProcess.spawn(
            [shell, "-i"], cwd=settings["cwd"], env=env, dimensions=(rows, cols)
        )
    lock = threading.Lock()

    def emit(value: dict[str, Any]) -> None:
        with lock:
            sys.stdout.write(json.dumps(value, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    emit({"type": "ready", "pid": process.pid, "backend": "conpty" if os.name == "nt" else "pty"})

    def controls() -> None:
        try:
            while raw := sys.stdin.buffer.readline(32768):
                frame = json.loads(raw)
                if frame["type"] == "input":
                    data = base64.b64decode(frame["data_b64"], validate=True)
                    process.write(data.decode("utf-8") if os.name == "nt" else data)
                elif frame["type"] == "resize":
                    process.setwinsize(frame["rows"], frame["cols"])
                elif frame["type"] == "close":
                    break
        except (ValueError, EOFError, OSError) as exc:
            emit({"type": "error", "message": type(exc).__name__})
        finally:
            with contextlib.suppress(Exception):
                process.close(force=True)

    threading.Thread(target=controls, daemon=True).start()
    try:
        while True:
            output = process.read(4096)
            data = output.encode("utf-8") if isinstance(output, str) else output
            emit({"type": "output", "data_b64": base64.b64encode(data).decode()})
    except (EOFError, OSError):
        pass
    finally:
        with contextlib.suppress(Exception):
            process.close(force=True)
        emit({"type": "exit", "code": process.exitstatus})


if __name__ == "__main__":
    try:
        run()
    except Exception as failure:
        print(json.dumps({"type": "error", "message": f"PTY launch failed: {failure}"}), flush=True)
        sys.exit(1)
