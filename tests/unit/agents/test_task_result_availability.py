"""Reporting visibility follows the current delegated invocation, never the cached agent."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from langchain.agents.middleware import ModelRequest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.config import var_child_runnable_config
from tests.unit.agents.test_collaboration_resources import call
from tests.unit.agents.test_collaboration_resources import rig as rig

from octop.infra.agents.teams.task_results import build_task_result_tools


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en", "zh"])
async def test_direct_stale_call_explains_prerequisite_without_writes(
    rig: Any, language: str
) -> None:
    token = var_child_runnable_config.set(
        {"configurable": {"user": rig.owner, "thread_id": "root", "language": language}}
    )
    try:
        result = json.loads(
            await build_task_result_tools(rig.manager, "parent")[0].ainvoke(
                {"outcome": "succeeded", "summary": "Done"}
            )
        )
    finally:
        var_child_runnable_config.reset(token)
    assert result["code"] == "TASK_RESULT_NOT_APPLICABLE"
    assert result["status"] == "error" and result["retryable"] is False
    assert ("do not retry" if language == "en" else "不要重试") in result["error"]
    assert not rig.collaboration.listing(rig.owner, "parent", "root", 0, 100)["invocations"]


@pytest.mark.asyncio
async def test_nonempty_invalid_invocation_keeps_generic_denial(rig: Any) -> None:
    token = var_child_runnable_config.set(
        {"configurable": {"user": rig.owner, "thread_id": "root", "octop_invocation_id": "forged"}}
    )
    try:
        result = json.loads(
            await build_task_result_tools(rig.manager, "parent")[0].ainvoke(
                {"outcome": "succeeded", "summary": "Done"}
            )
        )
    finally:
        var_child_runnable_config.reset(token)
    assert result == {
        "status": "error",
        "code": "TASK_RESULT_DENIED",
        "retryable": False,
        "error": "Task result could not be recorded.",
    }


@pytest.mark.asyncio
async def test_visibility_reuses_request_in_direct_child_direct_and_concurrent_calls(
    rig: Any,
) -> None:
    from octop_harness.teams import DispatchReceipt

    from octop.infra.agents.middleware.task_results import TaskResultAvailabilityMiddleware

    peer = call(rig)
    rig.collaboration.accept(peer)
    rig.collaboration.bind(peer, "child-thread", {"octop_child_bound": True})
    await rig.collaboration.lifecycle(
        peer, DispatchReceipt(invocation_id="inv-1", transport_status="running")
    )
    middleware = TaskResultAvailabilityMiddleware(rig.manager, "child")
    tool = build_task_result_tools(rig.manager, "child")[0]
    request = ModelRequest(
        model=FakeListChatModel(responses=["unused"]),
        messages=[],
        tools=[
            tool,
            "report_task_result",
            {"name": "report_task_result"},
            {"type": "function", "function": {"name": "report_task_result"}},
            {"name": "other"},
        ],
    )
    child = {
        "user": rig.owner,
        "thread_id": "child-thread",
        "octop_child_bound": True,
        "octop_invocation_id": "inv-1",
    }

    async def visible(config: dict[str, Any], asynchronous: bool) -> list[Any]:
        token = var_child_runnable_config.set({"configurable": config})
        try:
            if asynchronous:

                async def handler(prepared: Any) -> Any:
                    await asyncio.sleep(0)
                    return prepared

                return (await middleware.awrap_model_call(request, handler)).tools
            return middleware.wrap_model_call(request, lambda prepared: prepared).tools
        finally:
            var_child_runnable_config.reset(token)

    direct = {"user": rig.owner, "thread_id": "unrelated"}
    for asynchronous in (False, True):
        assert await visible(direct, asynchronous) == [{"name": "other"}]
        assert await visible(child, asynchronous) == request.tools
        assert await visible(direct, asynchronous) == [{"name": "other"}]
    results = await asyncio.gather(visible(child, True), visible(direct, True))
    assert results == [request.tools, [{"name": "other"}]]
    assert len(request.tools) == 5

    for change in (
        {"user": rig.outsider},
        {"octop_invocation_id": "fake"},
        {"thread_id": "unrelated"},
        {"octop_child_bound": False},
    ):
        assert await visible({**child, **change}, True) == [{"name": "other"}]
    wrong_agent = TaskResultAvailabilityMiddleware(rig.manager, "parent")
    token = var_child_runnable_config.set({"configurable": child})
    try:
        assert wrong_agent.wrap_model_call(request, lambda prepared: prepared).tools == [
            {"name": "other"}
        ]
    finally:
        var_child_runnable_config.reset(token)
    await rig.collaboration.lifecycle(
        peer, DispatchReceipt(invocation_id="inv-1", transport_status="completed")
    )
    assert await visible(child, True) == [{"name": "other"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["client", "native"])
async def test_installed_tool_search_cannot_reload_hidden_report(rig: Any, mode: str) -> None:
    from octop_harness.middleware.tool_search import ToolSearchMiddleware
    from octop_harness.teams import DispatchReceipt

    from octop.infra.agents.middleware.task_results import TaskResultAvailabilityMiddleware

    peer = call(rig)
    rig.collaboration.accept(peer)
    rig.collaboration.bind(peer, "child-thread", {"octop_child_bound": True})
    await rig.collaboration.lifecycle(
        peer, DispatchReceipt(invocation_id="inv-1", transport_status="running")
    )
    tool = build_task_result_tools(rig.manager, "child")[0]
    availability = TaskResultAvailabilityMiddleware(rig.manager, "child")
    search = ToolSearchMiddleware(deferred_tools=frozenset({tool.name}), mode=mode)
    request = ModelRequest(
        model=FakeListChatModel(responses=["unused"]),
        messages=[],
        tools=[tool],
        state={"messages": [], "loaded_tool_names": [tool.name]},
    )
    child = {
        "user": rig.owner,
        "thread_id": "child-thread",
        "octop_child_bound": True,
        "octop_invocation_id": "inv-1",
    }
    direct = {"user": rig.owner, "thread_id": "child-thread"}
    for config in (direct, child, direct):
        token = var_child_runnable_config.set({"configurable": config})
        try:

            async def capture(prepared: Any) -> Any:
                return prepared.tools

            async def through_search(prepared: Any) -> Any:
                return await search.awrap_model_call(prepared, capture)

            tools = await availability.awrap_model_call(request, through_search)
            assert (tool.name in [item.name for item in tools]) == bool(
                config.get("octop_invocation_id")
            )
            if mode == "client" and config is direct:
                assert not search._catalog(search._request_thread_key())
        finally:
            var_child_runnable_config.reset(token)


def test_tool_description_limits_reporting_to_delegated_child(rig: Any) -> None:
    description = build_task_result_tools(rig.manager, "child")[0].description
    assert "delegated task" in description and "child invocation" in description
    assert "Ordinary conversations should answer directly" in description


def test_report_registration_is_middleware_owned(rig: Any) -> None:
    from octop.infra.agents.middleware.task_results import TaskResultAvailabilityMiddleware

    assert [tool.name for tool in TaskResultAvailabilityMiddleware(rig.manager, "child").tools] == [
        "report_task_result"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, TypeError, ValueError])
async def test_unexpected_storage_failure_is_private_unavailable(
    rig: Any, monkeypatch: Any, caplog: Any, error_type: type[Exception]
) -> None:
    private = "TASK_RESULT_PRIVATE-config-summary-resource-sentinel"
    monkeypatch.setattr(
        rig.repos.collaboration_repo,
        "get",
        lambda *args: (_ for _ in ()).throw(error_type(private)),
    )
    token = var_child_runnable_config.set(
        {"configurable": {"user": rig.owner, "thread_id": "root", "octop_invocation_id": "opaque"}}
    )
    try:
        result = json.loads(
            await build_task_result_tools(rig.manager, "parent")[0].ainvoke(
                {"outcome": "succeeded", "summary": private}
            )
        )
    finally:
        var_child_runnable_config.reset(token)
    assert result["code"] == "TASK_RESULT_UNAVAILABLE"
    assert result["retryable"] is False and result["status"] == "error"
    assert private not in json.dumps(result) + caplog.text
    assert error_type.__name__ in caplog.text


@pytest.mark.asyncio
async def test_inner_input_validation_keeps_denied_semantics(rig: Any, caplog: Any) -> None:
    token = var_child_runnable_config.set(
        {"configurable": {"user": rig.owner, "octop_invocation_id": "opaque"}}
    )
    try:
        result = json.loads(
            await build_task_result_tools(rig.manager, "parent")[0].coroutine(
                outcome="succeeded", summary=""
            )
        )
    finally:
        var_child_runnable_config.reset(token)
    assert result["code"] == "TASK_RESULT_DENIED" and result["retryable"] is False
    assert not caplog.records


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [TypeError, ValueError])
async def test_availability_unexpected_value_errors_log_class_only(
    rig: Any, monkeypatch: Any, caplog: Any, error_type: type[Exception]
) -> None:
    from octop.infra.agents.middleware.task_results import TaskResultAvailabilityMiddleware

    private = "PRIVATE-repository-json-sentinel"

    def unavailable(*args: Any) -> Any:
        raise error_type(private)

    monkeypatch.setattr(rig.repos.collaboration_repo, "get", unavailable)
    middleware = TaskResultAvailabilityMiddleware(rig.manager, "child")
    request = ModelRequest(
        model=FakeListChatModel(responses=["unused"]), messages=[], tools=middleware.tools
    )
    token = var_child_runnable_config.set(
        {"configurable": {"user": rig.owner, "octop_invocation_id": "opaque"}}
    )
    try:
        assert middleware.wrap_model_call(request, lambda prepared: prepared).tools == []

        async def handler(prepared: Any) -> Any:
            return prepared

        assert (await middleware.awrap_model_call(request, handler)).tools == []
    finally:
        var_child_runnable_config.reset(token)
    assert error_type.__name__ in caplog.text and private not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("delegated,disabled", [(False, False), (True, False), (True, True)])
async def test_installed_harness_stream_registers_main_tool_without_subagent_inheritance(
    rig: Any, monkeypatch: Any, delegated: bool, disabled: bool
) -> None:
    from pathlib import Path

    from deepagents.middleware import subagents
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage
    from octop_harness.agent import HarnessAgent
    from octop_harness.config import HarnessAgentConfig
    from octop_harness.middleware.tools_filter import ToolsFilterMiddleware
    from octop_harness.teams import DispatchReceipt

    from octop.infra.agents.middleware.task_results import TaskResultAvailabilityMiddleware

    peer = call(rig)
    rig.collaboration.accept(peer)
    rig.collaboration.bind(peer, "child-thread", {"octop_child_bound": True})
    await rig.collaboration.lifecycle(
        peer, DispatchReceipt(invocation_id="inv-1", transport_status="running")
    )
    seen: list[list[str]] = []

    class Model(FakeMessagesListChatModel):
        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
            seen.append([getattr(tool, "name", "") for tool in tools])
            return self

    responses = [AIMessage(content="Done")]
    if not disabled:
        responses.insert(
            0,
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "report_task_result",
                        "args": {"outcome": "succeeded", "summary": "Done"},
                        "id": "report",
                    }
                ],
            ),
        )
    config = HarnessAgentConfig(
        providers=[],
        subagents_auto_load=False,
        subagents=[{"name": "custom", "description": "Worker", "system_prompt": "Help."}],
        tools_disabled=frozenset({"report_task_result"}) if disabled else frozenset(),
    )
    harness = HarnessAgent.__new__(HarnessAgent)
    harness._config = config
    harness._backend = None
    monkeypatch.setattr(harness, "_resolve_checkpointer", lambda: None)
    monkeypatch.setattr(harness, "_build_seed_model", lambda: Model(responses=responses))
    monkeypatch.setattr(harness, "_agent_visible_workspace_dir", Path.cwd)
    monkeypatch.setattr(harness, "_resolve_interrupt_on", lambda: None)
    original = subagents.create_sub_agent
    compiled: dict[str, list[str]] = {}

    def capture(spec: Any, **kwargs: Any) -> Any:
        compiled[spec["name"]] = [getattr(tool, "name", "") for tool in spec["tools"]]
        return original(spec, **kwargs)

    monkeypatch.setattr(subagents, "create_sub_agent", capture)
    graph = harness._build_graph(
        tools=[],
        middleware=[
            TaskResultAvailabilityMiddleware(rig.manager, "child"),
            ToolsFilterMiddleware(config=config),
        ],
        skills=[],
        memory=[],
    )
    assert set(compiled) == {"custom", "general-purpose"}
    assert all("report_task_result" not in tools for tools in compiled.values())
    cfg = {"user": rig.owner, "thread_id": "child-thread"}
    if delegated:
        cfg.update(octop_invocation_id="inv-1", octop_child_bound=True)
    states = [
        state
        async for state in graph.astream(
            {"messages": [{"role": "user", "content": "Probe"}]},
            config={"configurable": cfg},
            stream_mode="values",
        )
    ]
    assert seen and all(
        ("report_task_result" in tools) == (delegated and not disabled) for tools in seen
    )
    results = [message for message in states[-1]["messages"] if message.type == "tool"]
    if not disabled:
        result = json.loads(results[0].content)
        assert (
            result == {"status": "pending", "outcome": "succeeded"}
            if delegated
            else result["code"] == "TASK_RESULT_NOT_APPLICABLE"
        )


@pytest.mark.asyncio
async def test_without_context_hides_tool_and_missing_runtime_config_is_safe(rig: Any) -> None:
    from octop.infra.agents.middleware.task_results import TaskResultAvailabilityMiddleware

    middleware = TaskResultAvailabilityMiddleware(rig.manager, "child")
    request = ModelRequest(
        model=FakeListChatModel(responses=["unused"]), messages=[], tools=middleware.tools
    )
    assert middleware.wrap_model_call(request, lambda prepared: prepared).tools == []
    result = json.loads(
        await middleware.tools[0].ainvoke({"outcome": "succeeded", "summary": "Done"})
    )
    assert result["code"] == "TASK_RESULT_NOT_APPLICABLE"


@pytest.mark.asyncio
async def test_restart_reconciled_child_config_cannot_advertise_report(rig: Any) -> None:
    from octop_harness.teams import DispatchReceipt

    from octop.infra.agents.middleware.task_results import TaskResultAvailabilityMiddleware

    peer = call(rig)
    rig.collaboration.accept(peer)
    rig.collaboration.bind(peer, "child-thread", {"octop_child_bound": True})
    await rig.collaboration.lifecycle(
        peer, DispatchReceipt(invocation_id="inv-1", transport_status="running")
    )
    rig.collaboration.reconcile_startup()
    middleware = TaskResultAvailabilityMiddleware(rig.manager, "child")
    request = ModelRequest(
        model=FakeListChatModel(responses=["unused"]), messages=[], tools=middleware.tools
    )
    token = var_child_runnable_config.set(
        {
            "configurable": {
                "user": rig.owner,
                "thread_id": "child-thread",
                "octop_invocation_id": "inv-1",
                "octop_child_bound": True,
            }
        }
    )
    try:
        assert middleware.wrap_model_call(request, lambda prepared: prepared).tools == []
    finally:
        var_child_runnable_config.reset(token)


@pytest.mark.asyncio
async def test_save_then_raise_never_claims_confirmed_success(
    rig: Any, monkeypatch: Any, caplog: Any
) -> None:
    from octop_harness.teams import DispatchReceipt

    from octop.infra.agents.middleware.task_results import TaskResultAvailabilityMiddleware

    peer = call(rig)
    rig.collaboration.accept(peer)
    rig.collaboration.bind(peer, "child-thread", {"octop_child_bound": True})
    await rig.collaboration.lifecycle(
        peer, DispatchReceipt(invocation_id="inv-1", transport_status="running")
    )
    save = rig.repos.collaboration_repo.save
    private = "PRIVATE-after-commit-sentinel"

    def save_then_raise(*args: Any, **kwargs: Any) -> Any:
        save(*args, **kwargs)
        raise RuntimeError(private)

    monkeypatch.setattr(rig.repos.collaboration_repo, "save", save_then_raise)
    cfg = {
        "user": rig.owner,
        "thread_id": "child-thread",
        "octop_child_bound": True,
        "octop_invocation_id": "inv-1",
    }
    token = var_child_runnable_config.set({"configurable": cfg})
    try:
        result = json.loads(
            await build_task_result_tools(rig.manager, "child")[0].ainvoke(
                {"outcome": "succeeded", "summary": private}
            )
        )
        assert result["code"] == "TASK_RESULT_UNAVAILABLE" and result["retryable"] is False
        assert private not in json.dumps(result) + caplog.text
        stored = rig.repos.collaboration_repo.get("collaboration_invocations", rig.owner, "inv-1")
        assert stored["pending_task_result"]
        assert stored["task_outcome"] == "unknown" and "task_result" not in stored

        def unavailable(*args: Any) -> Any:
            raise RuntimeError(private)

        monkeypatch.setattr(rig.repos.collaboration_repo, "get", unavailable)
        middleware = TaskResultAvailabilityMiddleware(rig.manager, "child")
        request = ModelRequest(
            model=FakeListChatModel(responses=["unused"]), messages=[], tools=middleware.tools
        )
        assert middleware.wrap_model_call(request, lambda prepared: prepared).tools == []

        async def inspect(prepared: Any) -> Any:
            return prepared

        assert (await middleware.awrap_model_call(request, inspect)).tools == []
        assert private not in caplog.text

        def downstream_failure(prepared: Any) -> Any:
            raise RuntimeError("downstream")

        with pytest.raises(RuntimeError, match="downstream"):
            middleware.wrap_model_call(request, downstream_failure)

        async def downstream_async_failure(prepared: Any) -> Any:
            raise RuntimeError("downstream")

        with pytest.raises(RuntimeError, match="downstream"):
            await middleware.awrap_model_call(request, downstream_async_failure)
    finally:
        var_child_runnable_config.reset(token)
