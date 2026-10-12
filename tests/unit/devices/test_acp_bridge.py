"""ACP bytes run on the selected device, with no manager-host fallback."""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from octop_harness.acp.models import ACPConfig, ACPRunnerConfig, ACPSessionError

from octop.infra.devices.acp_bridge import RemoteACPService
from octop.infra.devices.executor import DeviceExecutionError, DeviceExecutor


class DeviceLink:
    def __init__(self, executor: DeviceExecutor, root: Path) -> None:
        self.executor = executor
        self.row = SimpleNamespace(
            roots=[{"id": "shared", "path": str(root), "read": True, "write": True}],
            platform="windows" if sys.platform == "win32" else "linux",
            permissions=["acp_run"],
            capabilities=["acp_run"],
            grant_version=1,
        )
        self.actions: list[str] = []
        self.open_params: dict[str, Any] | None = None

    def owned(self, owner: int, device_id: str) -> Any:
        assert owner == 7 and device_id == "target-device"
        return self.row

    async def call(
        self,
        owner: int,
        device_id: str,
        action: str,
        params: dict[str, Any],
        *,
        agent_id: str,
        expected_version: int,
        allow_acp: bool,
    ) -> dict[str, Any]:
        assert (owner, device_id, agent_id, expected_version, allow_acp) == (
            7,
            "target-device",
            "expert",
            1,
            True,
        )
        self.actions.append(action)
        if action == "acp.open":
            self.open_params = params.copy()
        return await self.executor.execute(
            uuid.uuid4().hex,
            action,
            params,
            grant_version=1,
            permissions=["acp_run"],
        )


@pytest.mark.asyncio
async def test_remote_acp_stream_uses_device_process_and_closes_it(tmp_path: Path) -> None:
    script = tmp_path / "echo.py"
    script.write_text(
        "import sys\n"
        "while line := sys.stdin.buffer.readline():\n"
        "    sys.stdout.buffer.write(line)\n"
        "    sys.stdout.buffer.flush()\n",
        encoding="utf-8",
    )
    root = tmp_path / "share"
    root.mkdir()
    roots = [{"id": "shared", "path": str(root), "read": True, "write": True}]
    executor = DeviceExecutor(["files_read", "files_write"], roots, acp_enabled=True)
    executor.update_grants(1, ["acp_run"], roots)
    link = DeviceLink(executor, root)
    service = RemoteACPService(
        config=ACPConfig(),
        devices=link,
        owner=7,
        agent_id="expert",
        device_id="target-device",
        root_id="shared",
    )
    runner = ACPRunnerConfig(enabled=True, command=sys.executable, args=[str(script)])
    try:
        async with service._transport(runner, 1) as (reader, writer, process):
            writer.write(b"from-manager\n")
            await writer.drain()
            assert await asyncio.wait_for(reader.readline(), 10) == b"from-manager\n"
            assert process.returncode is None
        assert link.actions[0] == "acp.open"
        assert "acp.write" in link.actions and "acp.poll" in link.actions
        assert link.actions[-1] == "acp.close"
        assert not executor._acp._sessions
    finally:
        await executor.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("runner_name", ["hermes", "grok_build", "openclaw"])
async def test_remote_runner_uses_device_environment_without_forwarding_hub_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner_name: str
) -> None:
    """Exercise the actual device subprocess with conflicting, synthetic credentials."""
    monkeypatch.setenv("OCTOP_ACP_TEST_TOKEN", "device-local-test-value")
    script = tmp_path / "environment.py"
    script.write_text(
        "import os, sys\n"
        "print(os.environ['OCTOP_ACP_TEST_TOKEN'], flush=True)\n"
        "sys.stdin.buffer.read()\n",
        encoding="utf-8",
    )
    root = tmp_path / "device-share"
    root.mkdir()
    roots = [{"id": "shared", "path": str(root), "read": True, "write": True}]
    executor = DeviceExecutor(["files_read", "files_write"], roots, acp_enabled=True)
    executor.update_grants(1, ["acp_run"], roots)
    link = DeviceLink(executor, root)
    runner = ACPRunnerConfig(
        enabled=True,
        command=sys.executable,
        args=[str(script)],
        env={"OCTOP_ACP_TEST_TOKEN": "hub-only-test-value"},
    )
    service = RemoteACPService(
        config=ACPConfig(runners={runner_name: runner}),
        devices=link,
        owner=7,
        agent_id="expert",
        device_id="target-device",
        root_id="shared",
    )
    try:
        async with service._transport(runner, 1, runner_name) as (reader, _, _):
            line = await asyncio.wait_for(reader.readline(), 10)
            assert line.rstrip(b"\r\n") == b"device-local-test-value"
            assert link.open_params == {
                "root_id": "shared",
                "runner": runner_name,
                "command": sys.executable,
                "args": [str(script)],
            }
        assert not executor._acp._sessions
    finally:
        await executor.close()


@pytest.mark.asyncio
async def test_remote_acp_turn_runs_in_device_shared_directory(tmp_path: Path) -> None:
    script = tmp_path / "fake_acp.py"
    script.write_text(
        "import json, pathlib, sys\n"
        "for line in sys.stdin:\n"
        "    request = json.loads(line)\n"
        "    method = request.get('method')\n"
        "    if method == 'initialize':\n"
        "        result = {'protocolVersion': 1}\n"
        "    elif method == 'session/new':\n"
        "        result = {'sessionId': 'device-session'}\n"
        "    elif method == 'session/prompt':\n"
        "        pathlib.Path('ran-on-device.txt').write_text('yes')\n"
        "        result = {'stopReason': 'end_turn'}\n"
        "    elif method == 'session/close':\n"
        "        result = {}\n"
        "    else:\n"
        "        result = {}\n"
        "    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)\n",
        encoding="utf-8",
    )
    root = tmp_path / "device-share"
    root.mkdir()
    roots = [{"id": "shared", "path": str(root), "read": True, "write": True}]
    executor = DeviceExecutor(["files_read", "files_write"], roots, acp_enabled=True)
    executor.update_grants(1, ["acp_run"], roots)
    link = DeviceLink(executor, root)
    runner = ACPRunnerConfig(enabled=True, command=sys.executable, args=[str(script)])
    service = RemoteACPService(
        config=ACPConfig(runners={"fake": runner}),
        devices=link,
        owner=7,
        agent_id="expert",
        device_id="target-device",
        root_id="shared",
    )
    try:
        result = await asyncio.wait_for(
            service.run_turn(
                thread_id="thread",
                runner="fake",
                prompt_blocks=[{"type": "text", "text": "work here"}],
                cwd=str(tmp_path / "manager-workspace"),
                on_message=lambda *_: asyncio.sleep(0),
            ),
            15,
        )
        assert result["status"] == "completed"
        assert (root / "ran-on-device.txt").read_text() == "yes"
        assert not (tmp_path / "manager-workspace" / "ran-on-device.txt").exists()
        await service.close_all_sessions()
        assert "acp.close" in link.actions
    finally:
        await executor.close()


@pytest.mark.asyncio
async def test_remote_acp_fails_closed_without_device_consent(tmp_path: Path) -> None:
    root = tmp_path / "share"
    root.mkdir()
    roots = [{"id": "shared", "path": str(root), "read": True, "write": True}]
    executor = DeviceExecutor(["files_read", "files_write"], roots)
    executor.update_grants(1, ["files_read", "files_write"], roots)
    link = DeviceLink(executor, root)
    link.row.permissions = []
    service = RemoteACPService(
        config=ACPConfig(),
        devices=link,
        owner=7,
        agent_id="expert",
        device_id="target-device",
        root_id="shared",
    )
    with pytest.raises(ACPSessionError, match="not authorized"):
        await service.run_turn(
            thread_id="thread",
            runner="opencode",
            prompt_blocks=[{"type": "text", "text": "hello"}],
            cwd=str(tmp_path),
            on_message=lambda *_: asyncio.sleep(0),
        )
    with pytest.raises(DeviceExecutionError, match="permission denied"):
        await executor.execute(
            uuid.uuid4().hex,
            "acp.open",
            {"root_id": "shared"},
            grant_version=1,
            permissions=["files_read", "files_write"],
        )
