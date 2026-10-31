# ruff: noqa: F811
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langgraph.config import var_child_runnable_config
from octop_harness.acp.models import ACPConfig

from octop.infra.devices.acp_bridge import RequestACPService, build_request_acp_tool
from octop.infra.devices.acp_process import DeviceACPProcesses
from octop.infra.devices.acp_settings import DeviceACPSettings
from octop.infra.errors import OctopError
from tests.unit.devices.test_service import enroll, rig  # noqa: F401, F811


@pytest.mark.asyncio
async def test_permission_response_uses_harness_session_id():
    request = RequestACPService(config=ACPConfig(), devices=None, owner=7, agent_id="expert")
    service = AsyncMock()
    service._find_session_by_acp_id.return_value = object()
    service.resume_permission.return_value = {"status": "completed"}
    request._session_targets[("thread", "opencode")] = service
    result = await request.resume_permission(
        acp_session_id="session", option_id="allow", on_message=None
    )
    assert result["status"] == "completed"
    service.resume_permission.assert_awaited_once_with(
        acp_session_id="session", option_id="allow", on_message=None
    )


def test_startup_check_does_not_claim_authentication():
    found = DeviceACPProcesses.check(sys.executable, [])
    assert found["available"] is True
    assert found["authentication"] == "not_checked"
    assert DeviceACPProcesses.check("missing-acp-program-239184", [])["available"] is False


@pytest.mark.skipif(os.name != "nt", reason="Windows system proxy integration")
def test_windows_proxy_is_local_and_explicit_environment_wins(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.getproxies",
        lambda: {"http": "http://system:7890", "https": "http://system:7890"},
    )
    monkeypatch.setenv("HTTPS_PROXY", "http://explicit:1234")
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    env = DeviceACPProcesses.process_environment()
    assert env["HTTPS_PROXY"] == "http://explicit:1234"
    assert env["HTTP_PROXY"] == "http://system:7890"
    assert "HTTP_PROXY" not in os.environ


def test_device_settings_are_owned_isolated_and_secret_free(rig):
    service, owner, other, _ = rig
    a, b = [enroll(service, owner)["device"]["device_id"] for _ in range(2)]
    sa, sb = DeviceACPSettings(service, owner, a), DeviceACPSettings(service, owner, b)
    original = sb.runners()["opencode"]
    sa.save("opencode", {**original, "command": "a-device-only", "enabled": True})
    assert sa.runners()["opencode"]["command"] == "a-device-only"
    assert sb.runners()["opencode"] == original
    with pytest.raises(OctopError):
        DeviceACPSettings(service, other, a)
    with pytest.raises(ValueError):
        sa.save("opencode", {**original, "env": {"KEY": "secret"}})
    sa.reset("opencode")
    assert sa.runners()["opencode"] == original


@pytest.mark.asyncio
async def test_selected_device_changes_new_sessions_and_preserves_existing(rig, monkeypatch):
    service, owner, _, root = rig
    a, b = [enroll(service, owner)["device"]["device_id"] for _ in range(2)]
    for device, command in [(a, "a-runner"), (b, "b-runner")]:
        store = DeviceACPSettings(service, owner, device)
        store.save("opencode", {**store.runners()["opencode"], "command": command, "enabled": True})
    context = SimpleNamespace(
        device_id=a,
        working_dir=str(root),
        policy_revision=1,
        grant_version=1,
        work_mode="agentic",
        context_id="ctx",
        target_kind="device",
    )
    monkeypatch.setattr("octop.infra.execution.service.ExecutionService.get", lambda *args: context)
    monkeypatch.setattr(
        service,
        "owned",
        lambda *args: SimpleNamespace(
            policy_revision=1,
            grant_version=1,
            permissions=["acp_run"],
            platform="windows",
            working_dir=str(root),
        ),
    )
    monkeypatch.setattr(service, "owner_trusted", lambda row: True)
    request = RequestACPService(config=ACPConfig(), devices=service, owner=owner, agent_id="writer")
    token = var_child_runnable_config.set(
        {
            "configurable": {
                "user": owner,
                "thread_id": "t",
                "octop_execution_context": {"context_id": "ctx"},
            }
        }
    )
    try:
        first = request._selected()
        assert first.config.runners["opencode"].command == "a-runner"
        request._session_targets[("t", "opencode")] = first
        context.device_id = b
        second = request._selected()
        assert second.config.runners["opencode"].command == "b-runner"
        assert first is not second
        assert request._session_targets[("t", "opencode")] is first
        tool = build_request_acp_tool("unregistered", ACPConfig(), root)
        result = await tool.ainvoke({"action": "start", "runner": "opencode", "message": "test"})
        assert isinstance(result, str)  # Missing service is a tool error, never a chat exception.
        from octop.infra.devices.acp_bridge import bind_remote_acp_service

        delegate = SimpleNamespace(ainvoke=AsyncMock(return_value="ok"))
        monkeypatch.setattr(
            "octop_harness.builtin.tools.acp_runner.build_acp_runner_tool",
            lambda **kwargs: delegate,
        )
        bind_remote_acp_service("acp-device-settings-test", request)
        tool = build_request_acp_tool("acp-device-settings-test", ACPConfig(), root)
        assert (
            await tool.ainvoke({"action": "start", "runner": "opencode", "message": "test"}) == "ok"
        )
        assert delegate.ainvoke.await_args.args[0]["cwd"] == str(root)
    finally:
        var_child_runnable_config.reset(token)
