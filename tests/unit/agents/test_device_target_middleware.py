from types import SimpleNamespace

from langchain.agents.middleware import ModelRequest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import SystemMessage
from langgraph.config import var_child_runnable_config

from octop.infra.agents.middleware.device_target import DeviceTargetMiddleware


def test_selected_device_context_routes_away_from_management_host():
    calls = []

    def owned(uid, target):
        calls.append((uid, target))
        return SimpleNamespace(
            name="GPU",
            permissions=["files_read"],
            roots=[{"id": "exp", "path": "/experiments"}],
            working_dir=None,
            runtime_metadata={},
            applied_trust_mode="restricted",
        )

    middleware = DeviceTargetMiddleware(SimpleNamespace(owned=owned), None, None)
    request = ModelRequest(
        model=FakeListChatModel(responses=["ok"]),
        messages=[],
        system_message=SystemMessage(content="existing rules"),
        tools=["read_file", "execute", "device_call", "device_request_access"],
    )
    token = var_child_runnable_config.set(
        {"configurable": {"user": "7", "octop_device_target": {"device_id": "gpu"}}}
    )
    try:
        result = middleware._prepare(request)
        assert calls == [(7, "gpu")]
        assert "existing rules" in result.system_message.content
        assert '"device_id": "gpu"' in result.system_message.content
        assert "/experiments" in result.system_message.content
        assert result.tools == ["device_call", "device_request_access"]
        assert request.tools[0] == "read_file"
    finally:
        var_child_runnable_config.reset(token)


def test_routed_device_keeps_expert_storage_on_controller():
    device = SimpleNamespace(
        name="GPU",
        permissions=["files_read", "files_write", "command_exec"],
        roots=[],
        working_dir="/home/gpu/project",
        runtime_metadata={},
        applied_trust_mode="owner",
    )
    middleware = DeviceTargetMiddleware(
        SimpleNamespace(owned=lambda uid, target: device), "gpu", None, routed_backend=True
    )
    request = ModelRequest(
        model=FakeListChatModel(responses=["ok"]),
        messages=[],
        system_message=SystemMessage(content="existing rules"),
        tools=["read_file", "edit_file", "execute"],
    )
    token = var_child_runnable_config.set(
        {
            "configurable": {
                "user": "7",
                "octop_execution_context": {
                    "target_kind": "device",
                    "device_id": "gpu",
                    "working_dir": "/home/gpu/selected-project",
                },
            }
        }
    )
    try:
        result = middleware._prepare(request)
        assert result.tools == request.tools
        content = str(result.system_message.content)
        assert "existing rules" in content
        assert "control center's storage backend" in content
        assert "different machine" in content
        assert "device shell permission error does not diagnose" in content
        assert "/home/gpu/selected-project" in content
    finally:
        var_child_runnable_config.reset(token)
