"""A real checkpoint must resume without replaying human messages or tools."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import Send
from octop_harness import HarnessAgent

from octop.config import OctopConfig
from octop.infra.agents.manager import AgentManager
from octop.infra.agents.response_recovery import (
    ResponseRecovery,
    ResumeModelProtocol,
    recovery_request,
)
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.errors import OctopError
from octop.infra.utils.paths import PathLayout


@asynccontextmanager
async def invocation(*args):
    yield


@pytest.fixture
def scenario(tmp_path):
    paths = PathLayout(tmp_path / "octop")
    paths.ensure_root()
    db = SqlitePool(paths.db)
    run_migrations(db)
    services = build_shared_services(db=db, paths=paths, config=OctopConfig())
    repos = services.repos
    repos.user_repo.create(username="owner", password_hash="h", role="admin")
    repos.user_repo.create(username="other", password_hash="h", role="user")
    repos.agent_repo.create(agent_id="agent", user_id=1, name="Expert")
    repos.thread_repo.insert(
        thread_id="thread",
        agent_id="agent",
        user_id=1,
        channel_type="dashboard",
        session_key="session",
    )
    counts = {"tool": 0, "model": 0, "fail": True}
    contexts = []

    async def model(state):
        counts["model"] += 1
        contexts.append([message.id for message in state["messages"]])
        if isinstance(state["messages"][-1], HumanMessage):
            calls = [{"id": "call", "name": "write", "args": {}}]
            if counts.get("parallel"):
                calls.append({"id": "other-call", "name": "write", "args": {}})
            return {
                "messages": [
                    AIMessage(
                        content="",
                        id="tool-call",
                        tool_calls=calls,
                    )
                ]
            }
        if counts["fail"]:
            raise ConnectionError("provider unavailable")
        return {
            "messages": [
                AIMessage(
                    content="恢复后的答案",
                    id=f"answer-{counts['model']}",
                    usage_metadata={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
                )
            ]
        }

    async def tools(state):
        counts["tool"] += 1
        if counts.get("tool_fail"):
            raise ConnectionError("device disconnected after submission")
        return {
            "messages": [
                ToolMessage(content="already written", tool_call_id="call", id="tool-result")
            ]
        }

    builder = StateGraph(MessagesState)
    builder.add_node("model", model)
    builder.add_node("tools", tools)
    builder.add_edge(START, "model")

    def next_nodes(state):
        calls = getattr(state["messages"][-1], "tool_calls", ())
        return [Send("tools", state) for _ in calls] or END

    builder.add_conditional_edges("model", next_nodes)
    builder.add_edge("tools", "model")
    graph = builder.compile(checkpointer=InMemorySaver())
    harness = SimpleNamespace(
        graph=graph, _steering_runs={}, _cancel_events={}, _invocation=invocation
    )
    harness._iter_until_cancelled = MethodType(HarnessAgent._iter_until_cancelled, harness)
    harness._stream_with_steering = MethodType(HarnessAgent._stream_with_steering, harness)
    harness._get_protocol = lambda _: ResumeModelProtocol(graph=graph)
    harness._prepare_call = MethodType(HarnessAgent._prepare_call, harness)
    lock = asyncio.Lock()
    manager = SimpleNamespace(
        _repos=repos,
        get_agent=lambda _: harness,
        _thread_execution_lock=lambda *args: lock,
        _track_invocation=invocation,
        _device_service=None,
        get_config=lambda _: {},
        providers_for_agent=lambda _: SimpleNamespace(is_model_ref_usable=lambda ref: True),
        get_row=repos.agent_repo.get,
    )
    manager._prepare_stream_request = MethodType(AgentManager._prepare_stream_request, manager)
    service = ResponseRecovery(manager)
    human = HumanMessage(
        content=[
            {"type": "text", "text": "处理附件"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
        ],
        id="original-user",
    )
    request = {
        "source": "dashboard/octop-dashboard",
        "thread_id": "thread",
        "agent_id": "agent",
        "user": "1",
        "messages": [human],
        "model": "owner/model",
    }
    yield SimpleNamespace(
        graph=graph,
        counts=counts,
        service=service,
        human=human,
        request=request,
        lock=lock,
        harness=harness,
        manager=manager,
        repos=repos,
        tmp_path=tmp_path,
        contexts=contexts,
    )
    db.close()


async def fail_turn(value):
    with pytest.raises(ConnectionError) as failure:
        await value.graph.ainvoke(
            {"messages": [value.human]}, {"configurable": {"thread_id": "thread"}}
        )
    recovery = await value.service.record("agent", value.request, failure.value)
    assert recovery
    return recovery


@pytest.mark.asyncio
async def test_continue_after_failed_tool_reports_unknown_result_without_replaying_it(scenario):
    scenario.counts.update(tool_fail=True, fail=False)
    recovery = await fail_turn(scenario)
    assert recovery["action"] == "retry"
    chunks = [
        chunk
        async for chunk in scenario.service.stream(
            1, "agent", "thread", recovery["response_id"], "continue-tool"
        )
    ]
    assert any(c.get("phase") == "completed" for c in chunks)
    state = await scenario.graph.aget_state({"configurable": {"thread_id": "thread"}})
    messages = state.values["messages"]
    assert [m.type for m in messages] == ["human", "ai", "tool", "ai"]
    assert messages[2].status == "error" and messages[2].tool_call_id == "call"
    assert messages[-1].content == "恢复后的答案"
    assert scenario.counts["tool"] == 1


@pytest.mark.asyncio
async def test_parallel_failed_tool_tasks_do_not_offer_unsafe_recovery(scenario):
    scenario.counts.update(tool_fail=True, parallel=True)
    with pytest.raises(ConnectionError) as failure:
        await scenario.graph.ainvoke(
            {"messages": [scenario.human]}, {"configurable": {"thread_id": "thread"}}
        )
    assert await scenario.service.record("agent", scenario.request, failure.value) is None


@pytest.mark.asyncio
async def test_revoked_model_prevents_tool_recovery_before_checkpoint_change(scenario):
    scenario.counts.update(tool_fail=True)
    recovery = await fail_turn(scenario)
    config = {"configurable": {"thread_id": "thread"}}
    before = await scenario.graph.aget_state(config)
    scenario.manager.providers_for_agent = lambda _: SimpleNamespace(
        is_model_ref_usable=lambda _: False
    )
    with pytest.raises(OctopError):
        _ = [
            chunk
            async for chunk in scenario.service.stream(
                1, "agent", "thread", recovery["response_id"], "revoked-tool"
            )
        ]
    after = await scenario.graph.aget_state(config)
    assert before.config == after.config and scenario.counts["tool"] == 1


@pytest.mark.asyncio
async def test_retry_resumes_original_model_without_repeating_a_tool_or_user(scenario):
    value = scenario
    recovery = await fail_turn(value)
    value.counts["fail"] = False
    chunks = [
        chunk
        async for chunk in value.service.stream(
            1, "agent", "thread", recovery["response_id"], "command"
        )
    ]
    state = await value.graph.aget_state({"configurable": {"thread_id": "thread"}})
    human = [message for message in state.values["messages"] if isinstance(message, HumanMessage)]
    assert len(human) == 1
    assert human[0].content == value.human.content
    assert value.counts["tool"] == 1
    assert state.values["messages"][-1].content == "恢复后的答案"
    assert not any(chunk["type"] == "user" for chunk in chunks)
    before = dict(value.counts)
    replay = [
        chunk
        async for chunk in value.service.stream(
            1, "agent", "thread", recovery["response_id"], "command"
        )
    ]
    assert replay[0]["status"] == "completed"
    assert value.counts == before


@pytest.mark.asyncio
async def test_later_message_invalidates_original_retry(scenario):
    recovery = await fail_turn(scenario)
    await scenario.graph.aupdate_state(
        {"configurable": {"thread_id": "thread"}},
        {"messages": [HumanMessage(content="new input", id="new-user")]},
    )
    with pytest.raises(OctopError, match="STALE"):
        _ = [
            chunk
            async for chunk in scenario.service.stream(
                1, "agent", "thread", recovery["response_id"], "stale"
            )
        ]
    assert scenario.counts["tool"] == 1


@pytest.mark.asyncio
async def test_other_account_cannot_recover_a_response(scenario):
    recovery = await fail_turn(scenario)
    with pytest.raises(OctopError) as error:
        _ = [
            chunk
            async for chunk in scenario.service.stream(
                2, "agent", "thread", recovery["response_id"], "foreign"
            )
        ]
    assert error.value.status == 404


@pytest.mark.asyncio
async def test_busy_thread_is_not_interrupted_or_queued_by_retry(scenario):
    recovery = await fail_turn(scenario)
    async with scenario.lock:
        with pytest.raises(OctopError, match="BUSY"):
            _ = [
                chunk
                async for chunk in scenario.service.stream(
                    1, "agent", "thread", recovery["response_id"], "busy"
                )
            ]


@pytest.mark.asyncio
async def test_disconnect_after_ack_finalizes_retry_without_replaying(scenario):
    recovery = await fail_turn(scenario)
    before = dict(scenario.counts)
    stream = scenario.service.stream(1, "agent", "thread", recovery["response_id"], "disconnect")
    assert (await anext(stream))["status"] == "accepted"
    await stream.aclose()
    receipt = scenario.repos.run_event_repo.get(1, "chat-retry:1:disconnect")
    assert receipt["status"] == "unknown"
    assert not scenario.lock.locked()
    replay = [
        chunk
        async for chunk in scenario.service.stream(
            1, "agent", "thread", recovery["response_id"], "disconnect"
        )
    ]
    assert replay[0]["status"] == "unknown"
    assert scenario.counts == before


@pytest.mark.asyncio
async def test_gateway_disconnect_closes_recovery_before_returning(scenario):
    from octop.infra.gateway.process.response_recovery import iter_response_recovery

    recovery = await fail_turn(scenario)
    processor = MagicMock()
    processor._agent_trajectory_enabled.return_value = False
    processor._begin_history = AsyncMock(return_value=None)
    stream = iter_response_recovery(
        manager=scenario.manager,
        processor=processor,
        owner=1,
        agent="agent",
        thread="thread",
        response_id=recovery["response_id"],
        command_id="gateway-disconnect",
        locale="en",
    )
    assert (await anext(stream))["status"] == "accepted"
    await stream.aclose()
    receipt = scenario.repos.run_event_repo.get(1, "chat-retry:1:gateway-disconnect")
    assert receipt["status"] == "unknown" and not scenario.lock.locked()


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", [b"accepted", b"run_phase"])
async def test_asgi_disconnect_while_sending_event_closes_recovery(scenario, monkeypatch, boundary):
    from starlette.requests import Request

    from octop.api.routers.chat import response_recovery as api

    recovery = await fail_turn(scenario)
    before = dict(scenario.counts)
    processor = MagicMock()
    processor._agent_trajectory_enabled.return_value = False
    processor._begin_history = AsyncMock(return_value=None)
    server = MagicMock()
    server.app_runtime.agent_registry = scenario.manager
    server.app_runtime.gateway.processor = processor
    monkeypatch.setattr(api, "assert_agent_access", lambda *_: None)
    scope = {
        "type": "http",
        "asgi": {"spec_version": "2.3"},
        "method": "POST",
        "headers": [],
        "state": {},
    }
    sending_event = asyncio.Event()

    async def receive():
        await sending_event.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body" and boundary in message["body"]:
            sending_event.set()
            await asyncio.Event().wait()

    response = await api.recover_response(
        "agent",
        "thread",
        api.ResponseRecoveryBody(response_id=recovery["response_id"], command_id="asgi-disconnect"),
        Request(scope),
        user=SimpleNamespace(id=1),
        server=server,
    )
    try:
        await asyncio.wait_for(response(scope, receive, send), 5)
        assert sending_event.is_set()
        receipt = scenario.repos.run_event_repo.get(1, "chat-retry:1:asgi-disconnect")
        assert receipt["status"] == "unknown" and not scenario.lock.locked()
        assert not scenario.harness._steering_runs and not scenario.harness._cancel_events
        assert scenario.counts == before
    finally:
        await response.body_iterator.aclose()


def test_recovery_freezes_absent_execution_target(scenario):
    class NoExecutionSelection:
        @property
        def repos(self):
            raise AssertionError("Recovery must not consult a later execution selection")

    original = {"thread_id": "thread", "user": "1", "agent_id": "agent", "messages": []}
    saved = recovery_request(original)
    scenario.manager._device_service = NoExecutionSelection()
    prepared = scenario.manager._prepare_stream_request("agent", saved)
    assert prepared["configurable"]["octop_recovery_without_target"] is True
    assert not prepared["configurable"].get("octop_execution_context")


@pytest.mark.asyncio
async def test_successful_regeneration_also_keeps_original_user_and_tool(scenario):
    recovery = await fail_turn(scenario)
    scenario.counts["fail"] = False
    _ = [
        chunk
        async for chunk in scenario.service.stream(
            1, "agent", "thread", recovery["response_id"], "first"
        )
    ]
    latest = await scenario.service.latest(1, "agent", "thread")
    assert latest["action"] == "regenerate"
    _ = [
        chunk
        async for chunk in scenario.service.stream(
            1, "agent", "thread", latest["response_id"], "regenerate"
        )
    ]
    state = await scenario.graph.aget_state({"configurable": {"thread_id": "thread"}})
    assert len([m for m in state.values["messages"] if isinstance(m, HumanMessage)]) == 1
    assert scenario.counts["tool"] == 1


def test_recovery_configuration_contains_no_prompt_or_plugin_secrets():
    original = {
        "messages": ["secret body"],
        "thread_id": "t",
        "user": "1",
        "configurable": {
            "plugin_tool_configs": {"api_key": "secret"},
            "octop_execution_context": {"context_id": "ctx", "working_dir": "private"},
        },
    }
    saved = recovery_request(original)
    assert saved["messages"] == []
    assert saved["configurable"] == {"octop_execution_context": {"context_id": "ctx"}}


@pytest.mark.asyncio
async def test_model_switch_keeps_context_and_cannot_reuse_a_command_for_another_model(scenario):
    scenario.request["configurable"] = {
        "octop_reasoning_overrides": {"extra_body": {"enable_thinking": True}}
    }
    recovery = await fail_turn(scenario)
    scenario.counts["fail"] = False
    prepared = MagicMock(side_effect=lambda _agent, request: request)
    scenario.manager._prepare_stream_request = prepared
    _ = [
        chunk
        async for chunk in scenario.service.stream(
            1, "agent", "thread", recovery["response_id"], "switch", "owner/other-model"
        )
    ]
    request = prepared.call_args.args[1]
    assert request["model"] == "owner/other-model"
    assert request["messages"] == []
    assert "octop_reasoning_overrides" not in request["configurable"]
    assert scenario.counts["tool"] == 1
    with pytest.raises(OctopError, match="COMMAND_CONFLICT"):
        _ = [
            chunk
            async for chunk in scenario.service.stream(
                1, "agent", "thread", recovery["response_id"], "switch", "owner/third-model"
            )
        ]


@pytest.mark.asyncio
async def test_late_steering_followup_keeps_the_recovered_answer_as_context(scenario):
    recovery = await fail_turn(scenario)
    row = scenario.repos.run_event_repo.get(1, recovery["response_id"])
    config = {
        "configurable": {
            "thread_id": "thread",
            "checkpoint_id": row["payload"]["resume_checkpoint_id"],
        }
    }
    protocol = ResumeModelProtocol(graph=scenario.graph)
    scenario.counts["fail"] = False
    _ = [chunk async for chunk in protocol.stream([], config)]
    first_answer = f"answer-{scenario.counts['model']}"
    _ = [chunk async for chunk in protocol.stream([], config)]
    assert first_answer in scenario.contexts[-1]
    assert scenario.counts["tool"] == 1


@pytest.mark.asyncio
async def test_recovery_rechecks_knowledge_access_before_any_model_call(scenario):
    scenario.request["configurable"] = {"knowledge_base_ids": ["no-longer-visible"]}
    recovery = await fail_turn(scenario)
    before = dict(scenario.counts)
    with pytest.raises(OctopError) as error:
        _ = [
            chunk
            async for chunk in scenario.service.stream(
                1, "agent", "thread", recovery["response_id"], "revoked"
            )
        ]
    assert error.value.status == 403
    assert scenario.counts == before


@pytest.mark.asyncio
async def test_http_recovery_archives_only_new_output_and_deduplicates_reconnect(scenario):
    import httpx
    from fastapi import FastAPI
    from langchain_core.messages import messages_from_dict

    from octop.api.deps import current_user, get_server
    from octop.api.routers.chat.response_recovery import router
    from octop.infra.gateway.process.processor import GlobalProcessor
    from octop.infra.gateway.slash.dispatcher import SlashDispatcher
    from octop.infra.history.service import HistoryArchive
    from octop.infra.history.store import HistoryStore

    store = HistoryStore(scenario.tmp_path / "history.sqlite", identity="recovery-test")
    archive = HistoryArchive(
        store,
        scenario.repos.thread_message_repo,
        scenario.repos.trajectory_event_repo,
        enabled=True,
    )
    gateway = SimpleNamespace(emit_thread_changed=AsyncMock())
    usage_repo = MagicMock()
    processor = GlobalProcessor(
        agent_manager=scenario.manager,
        thread_registry=MagicMock(),
        audit_repo=scenario.repos.audit_repo,
        agent_repo=scenario.repos.agent_repo,
        user_repo=scenario.repos.user_repo,
        connector_repo=scenario.repos.connector_repo,
        dispatcher=SlashDispatcher(),
        thread_message_repo=scenario.repos.thread_message_repo,
        history_archive=archive,
        gateway=gateway,
        usage_repo=usage_repo,
    )
    original = await processor._begin_history("agent", "thread", scenario.request)
    recovery = await fail_turn(scenario)
    failed_state = await scenario.graph.aget_state({"configurable": {"thread_id": "thread"}})
    original.observe({"type": "state_snapshot", "data": failed_state.values})
    original.observe({"type": "error", "message": "provider unavailable"})
    await processor._complete_resumed_history("thread", original, completed=False)
    scenario.counts["fail"] = False
    server = SimpleNamespace(
        app_runtime=SimpleNamespace(
            agent_registry=scenario.manager,
            gateway=SimpleNamespace(processor=processor),
        )
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=1, is_admin=True)
    app.dependency_overrides[get_server] = lambda: server
    url = "/agents/agent/threads/thread/response-recovery"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            latest = await client.get(url)
            assert latest.status_code == 200
            assert latest.json()["response_id"] == recovery["response_id"]
            command = {"response_id": recovery["response_id"], "command_id": "http-retry"}
            response = await client.post(url, json=command, headers={"Accept-Language": "zh"})
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert '"type": "error"' not in response.text
            assert '"type": "done"' in response.text
            before = dict(scenario.counts)
            duplicate = await client.post(url, json=command)
            assert '"status": "completed"' in duplicate.text
            assert scenario.counts == before

        async def no_legacy(_anchor):
            raise AssertionError("No checkpoint history fallback should be needed")

        page = await archive.page("thread", limit=100, cursor=None, legacy_reader=no_legacy)
        messages = messages_from_dict(page["messages"])
        assert len([message for message in messages if isinstance(message, HumanMessage)]) == 1
        assert len([message for message in messages if isinstance(message, ToolMessage)]) == 1
        assert messages[-1].content == "恢复后的答案"
        assert scenario.counts["tool"] == 1
        gateway.emit_thread_changed.assert_awaited_once_with(
            owner_user_id=1, agent_id="agent", thread_id="thread", reason="completed"
        )
        usage_repo.record.assert_called_once()
        assert usage_repo.record.call_args.kwargs["input_tokens"] == 7
        assert usage_repo.record.call_args.kwargs["output_tokens"] == 3
    finally:
        store.close()
