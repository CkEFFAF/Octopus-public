from unittest.mock import AsyncMock

import pytest
from langgraph.prebuilt.tool_node import ToolCallRequest

from octop.infra.agents.middleware import browser_profile


def _request(name: str, args: dict[str, object]) -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"name": name, "args": args, "id": "call-1"},
        tool=None,
        state={},
        runtime=None,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_browser_profile_is_forced_from_current_user(monkeypatch) -> None:
    monkeypatch.setattr(
        browser_profile,
        "get_config",
        lambda: {"configurable": {"user": "42"}},
    )
    handler = AsyncMock(return_value=object())
    request = _request("browser_use", {"action": "navigate", "profile": "default"})

    await browser_profile.BrowserProfileMiddleware().awrap_tool_call(request, handler)

    forwarded = handler.await_args.args[0]
    assert forwarded.tool_call["args"] == {
        "action": "navigate",
        "profile": "user-42",
    }


@pytest.mark.asyncio
async def test_non_browser_tool_is_unchanged(monkeypatch) -> None:
    monkeypatch.setattr(
        browser_profile,
        "get_config",
        lambda: {"configurable": {"user": "42"}},
    )
    handler = AsyncMock(return_value=object())
    request = _request("read_file", {"path": "notes.txt"})

    await browser_profile.BrowserProfileMiddleware().awrap_tool_call(request, handler)

    assert handler.await_args.args[0] is request


@pytest.mark.asyncio
async def test_browser_profile_blocks_when_user_missing(monkeypatch) -> None:
    monkeypatch.setattr(browser_profile, "get_config", lambda: {"configurable": {}})
    handler = AsyncMock(return_value=object())
    request = _request("browser_use", {"action": "navigate", "profile": "default"})

    result = await browser_profile.BrowserProfileMiddleware().awrap_tool_call(request, handler)

    handler.assert_not_awaited()
    assert getattr(result, "status", None) == "error"
    assert "no Octop user id" in str(result.content)


@pytest.mark.asyncio
async def test_browser_profile_blocks_placeholder_user_zero(monkeypatch) -> None:
    monkeypatch.setattr(
        browser_profile,
        "get_config",
        lambda: {"configurable": {"user": "0"}},
    )
    handler = AsyncMock(return_value=object())
    request = _request("browser_use", {"action": "navigate"})

    result = await browser_profile.BrowserProfileMiddleware().awrap_tool_call(request, handler)

    handler.assert_not_awaited()
    assert getattr(result, "status", None) == "error"


@pytest.mark.asyncio
async def test_selected_device_browser_uses_frozen_context_and_never_calls_host(
    monkeypatch,
) -> None:
    import json
    from types import SimpleNamespace

    cfg = {"user": "42", "octop_execution_context": {"context_id": "frozen-device"}}
    monkeypatch.setattr(browser_profile, "get_config", lambda: {"configurable": cfg})
    executions = SimpleNamespace(
        call=AsyncMock(return_value={"result": {"tabs": [], "session_id": "device-browser"}})
    )
    middleware = browser_profile.BrowserProfileMiddleware(executions, "expert")
    host = AsyncMock()
    result = await middleware.awrap_tool_call(
        _request(
            "browser_use",
            {"action": "goto", "url": "http://localhost:3000", "profile": "someone-else"},
        ),
        host,
    )
    assert json.loads(result.content)["success"] is True
    assert executions.call.await_args_list[-1].args == (
        42,
        "frozen-device",
        "browser.action",
        {"command": "navigate", "url": "http://localhost:3000"},
    )
    assert executions.call.await_args.kwargs == {"actor_agent_id": "expert"}
    host.assert_not_awaited()
    executions.call.side_effect = RuntimeError("selected device offline")
    failed = await middleware.awrap_tool_call(_request("browser_use", {"action": "dom_tree"}), host)
    assert failed.status == "error" and "offline" in failed.content
    host.assert_not_awaited()
    cfg.pop("octop_execution_context")
    cfg["octop_device_target"] = {"device_id": "selected"}
    failed = await middleware.awrap_tool_call(
        _request("browser_use", {"action": "screenshot"}), host
    )
    assert failed.status == "error" and "no execution context" in failed.content
    host.assert_not_awaited()
