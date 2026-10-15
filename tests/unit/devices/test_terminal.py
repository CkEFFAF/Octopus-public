"""Exercise native PTY/ConPTY rather than emulating a shell with command.run."""

from __future__ import annotations

import asyncio
import base64
import os
from pathlib import Path

import pytest

from octop.infra.devices.executor import DeviceExecutor
from octop.infra.devices.terminal import DeviceTerminals, supported

pytestmark = pytest.mark.skipif(not supported(), reason="native PTY dependency unavailable")


async def test_terminal_native_cwd_resize_reconnect_and_context_isolation(tmp_path: Path) -> None:
    manager = DeviceTerminals()
    params = {"session_id": "test-native", "execution_context_id": "frozen-context"}
    try:
        receipt = await manager.call("terminal.open", params, tmp_path)
        assert receipt["backend"] == ("conpty" if os.name == "nt" else "pty")
        assert receipt["cwd"] == str(tmp_path)
        assert (await manager.call("terminal.open", params, tmp_path))["resumed"] is True
        with pytest.raises(ValueError, match="context"):
            await manager.call(
                "terminal.poll", {**params, "execution_context_id": "other"}, tmp_path
            )
        await manager.call("terminal.resize", {**params, "cols": 100, "rows": 32}, tmp_path)
        command = (
            "Write-Output ('NATIVE_' + 'CWD=' + (Get-Location).Path)\r"
            if os.name == "nt"
            else "printf 'NATIVE_%s=%s\\n' CWD \"$PWD\"\r"
        )
        await manager.call(
            "terminal.input",
            {**params, "data_b64": base64.b64encode(command.encode()).decode()},
            tmp_path,
        )
        output = b""
        offset = 0
        deadline = asyncio.get_running_loop().time() + 15
        while asyncio.get_running_loop().time() < deadline:
            result = await manager.call("terminal.poll", {**params, "offset": offset}, tmp_path)
            output += base64.b64decode(result["data_b64"])
            offset = result["next_offset"]
            if f"NATIVE_CWD={tmp_path}".encode() in output:
                break
            await asyncio.sleep(0.1)
        assert f"NATIVE_CWD={tmp_path}".encode() in output, output.decode(errors="replace")
        assert (await manager.call("terminal.close", params, tmp_path))["closed"] is True
        assert not manager.sessions
    finally:
        await manager.close_all()


async def test_executor_transport_detach_preserves_terminal(tmp_path: Path) -> None:
    executor = DeviceExecutor(["command_exec"], [], trust_mode="owner", working_dir=str(tmp_path))
    params = {"session_id": "detach", "execution_context_id": "context"}
    try:
        await executor.execute(
            "open", "terminal.open", params, grant_version=0, permissions=["command_exec"]
        )
        await executor.close(preserve_terminals=True)
        receipt = await executor.execute(
            "reattach", "terminal.open", params, grant_version=0, permissions=["command_exec"]
        )
        assert receipt["resumed"] is True
        assert "open" not in executor._journal
    finally:
        await executor.close()


async def test_exited_terminal_drains_all_retained_output_before_eof(tmp_path: Path) -> None:
    manager = DeviceTerminals()
    params = {"session_id": "large-output", "execution_context_id": "context"}
    try:
        await manager.call("terminal.open", params, tmp_path)
        command = (
            "Write-Output ('x' * 70000); Write-Output 'TAIL_DONE'; exit\r"
            if os.name == "nt"
            else "printf '%70000s' x; printf 'TAIL_DONE\\n'; exit\r"
        )
        await manager.call(
            "terminal.input",
            {**params, "data_b64": base64.b64encode(command.encode()).decode()},
            tmp_path,
        )
        reader = manager.sessions[params["session_id"]].reader
        assert reader is not None
        await asyncio.wait_for(asyncio.shield(reader), 20)
        first = await manager.call("terminal.poll", {**params, "offset": 0}, tmp_path)
        assert first["eof"] is False
        output = base64.b64decode(first["data_b64"])
        page = first
        while not page["eof"]:
            page = await manager.call(
                "terminal.poll", {**params, "offset": page["next_offset"]}, tmp_path
            )
            output += base64.b64decode(page["data_b64"])
        assert len(output) == len(manager.sessions[params["session_id"]].output)
        assert len(output) > 70000
        assert b"TAIL_DONE" in output[-1000:]
    finally:
        await manager.close_all()
