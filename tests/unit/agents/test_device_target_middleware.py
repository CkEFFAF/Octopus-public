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
