"""Structured reports cross the installed Harness lifecycle and real SQLite history."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage
from langgraph.config import var_child_runnable_config
from octop_harness.middleware.peer import PeerAgentMiddleware
from octop_harness.teams.team_manager import TeamManager as HarnessTeam
from tests.unit.agents.test_collaboration_resources import call
from tests.unit.agents.test_collaboration_resources import rig as rig

from octop.infra.agents.teams.task_results import (
    TaskResultInput,
    TaskResultService,
    build_task_result_tools,
)
from octop.infra.agents.teams.team_manager import TeamManager
from octop.infra.errors import OctopError
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.history.projection import message_inputs


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("succeeded", "succeeded"),
        ("failed", "failed"),
        ("blocked", "blocked"),
        ("needs_input", "needs_input"),
        ("none", "unknown"),
        ("empty", "unknown"),
        ("prepersisted", "succeeded"),
        ("save_conflict", "unknown"),
        ("terminal_conflict", "unknown"),
        ("cancel_requested", "unknown"),
        ("abnormal", "unknown"),
        ("nested", "succeeded"),
        ("availability_failure", "unknown"),
    ],
)
async def test_installed_harness_report_result(
    rig: Any, mode: str, scenario: str, expected: str, monkeypatch: Any
) -> None:
    tool = build_task_result_tools(rig.manager, "child")[0]
    assert set(tool.args) == {"outcome", "summary", "resource_ids"}
    assert tool.args_schema.model_json_schema()["additionalProperties"] is False
    rig.manager._prepare_stream_request = lambda aid, request: request
    rig.manager.get_row = lambda aid: rig.repos.agent_repo.get(aid)
    rig.manager._team_jobs = None
    observed = []
    if scenario == "nested":
        rig.repos.agent_repo.create(agent_id="grandchild", user_id=rig.owner, name="grandchild")
        rig.workspaces["grandchild"] = rig.workspaces["child"]

    async def child(request: Any) -> dict[str, Any]:
        from langchain.agents.middleware import ModelRequest
        from langchain_core.language_models.fake_chat_models import FakeListChatModel

        from octop.infra.agents.middleware.task_results import TaskResultAvailabilityMiddleware

        current_agent = request.agent_id
        current_tool = build_task_result_tools(rig.manager, current_agent)[0]
        cfg = {
            **request.configurable,
            "user": rig.owner,
            "agent_id": current_agent,
            "thread_id": request.thread_id,
        }
        scope = var_child_runnable_config.set({"configurable": cfg})
        try:
            model_request = ModelRequest(
                model=FakeListChatModel(responses=["unused"]), messages=[], tools=[current_tool]
            )

            async def inspect_tools(prepared: Any) -> Any:
                return prepared.tools

            availability = TaskResultAvailabilityMiddleware(rig.manager, current_agent)
            if scenario == "availability_failure":

                def unavailable(*args: Any) -> Any:
                    raise RuntimeError("private-storage-failure")

                availability.service.bound_invocation = unavailable
            assert await availability.awrap_model_call(model_request, inspect_tools) == (
                [] if scenario == "availability_failure" else [current_tool]
            )
            if scenario == "nested" and current_agent == "child":
                nested_ask = next(
                    t
                    for t in PeerAgentMiddleware(harness, peer_invoke_mode="sync").tools
                    if t.name == "ask_agent"
                )
                nested = json.loads(
                    await nested_ask.ainvoke({"expert": "grandchild", "message": "Nested task"})
                )
                assert nested["dispatch_receipt"]["task_outcome"] == "succeeded"
                assert (
                    var_child_runnable_config.get()["configurable"]["octop_invocation_id"]
                    == cfg["octop_invocation_id"]
                )
            if scenario not in {"none", "availability_failure"}:
                report = {
                    "outcome": scenario
                    if scenario in {"failed", "blocked", "needs_input"}
                    else "succeeded",
                    "summary": "Public task summary",
                }
                first = json.loads(await current_tool.ainvoke(report))
                assert first["status"] == "pending", first
                assert json.loads(await current_tool.ainvoke(report)) == first
                conflict = json.loads(
                    await current_tool.ainvoke({**report, "summary": "Other claim"})
                )
                assert conflict["code"] == "TASK_RESULT_CONFLICT"
            if scenario == "cancel_requested":
                rig.collaboration.request_cancel(rig.owner, cfg["octop_invocation_id"])
                assert await availability.awrap_model_call(model_request, inspect_tools) == [
                    current_tool
                ]
                assert json.loads(await current_tool.ainvoke(report))["status"] == "pending"
            if scenario == "abnormal":
                raise RuntimeError("provider-private-error")
            messages = [
                AIMessage(
                    content="   " if scenario == "empty" else "Today traffic is 12 MB.",
                    id="final-" + request.thread_id,
                )
            ]
            if scenario == "prepersisted":
                room._ensure_projection(request.thread_id)
                rig.repos.thread_message_repo.append_if_ready(
                    request.thread_id, message_inputs(messages)
                )
            return {"messages": messages, "dispatch_receipt": {"task_outcome": "succeeded"}}
        finally:
            var_child_runnable_config.reset(scope)

    entries = {
        aid: SimpleNamespace(
            agent_id=aid,
            config=SimpleNamespace(name=aid, team_peers=None, peer_invoke_mode=None),
            metadata={"user_id": rig.owner, "name": aid},
            agent=SimpleNamespace(
                call=child
                if aid in {"child", "grandchild"}
                else AsyncMock(return_value={"messages": [AIMessage(content="Followup")]})
            ),
        )
        for aid in (
            ("parent", "child", "grandchild") if scenario == "nested" else ("parent", "child")
        )
    }
    registry = MagicMock()
    registry.get.side_effect = entries.__getitem__
    registry.list.return_value = list(entries.values())
    harness = HarnessTeam(registry)
    harness.set_processor(
        SimpleNamespace(compose_followup=lambda *a, **k: "Done", on_reply=AsyncMock())
    )
    rig.manager._harness_manager = SimpleNamespace(team=harness)
    room = TeamManager(
        agent_manager=rig.manager,
        thread_registry=ThreadRegistry(
            session_repo=rig.repos.session_repo, thread_repo=rig.repos.thread_repo
        ),
        user_repo=rig.repos.user_repo,
        thread_message_repo=rig.repos.thread_message_repo,
    )
    harness.bind_peer_session(
        prepare=room.prepare_peer_session,
        after=room.record_peer_turn,
        lifecycle=rig.collaboration.lifecycle,
    )
    if scenario in {"save_conflict", "terminal_conflict"}:
        save = rig.repos.collaboration_repo.save

        def rejecting(*args: Any, **kwargs: Any) -> bool:
            return (
                False
                if args[5]
                == (
                    "delegation.result_ready"
                    if scenario == "save_conflict"
                    else "delegation.completed"
                )
                else save(*args, **kwargs)
            )

        monkeypatch.setattr(rig.repos.collaboration_repo, "save", rejecting)
    ask = next(
        t
        for t in PeerAgentMiddleware(harness, peer_invoke_mode=mode).tools
        if t.name == "ask_agent"
    )
    scope = var_child_runnable_config.set(
        {
            "configurable": {
                "user": rig.owner,
                "agent_id": "parent",
                "thread_id": "root",
                "session_key": "parent:dashboard:1:dm",
                "conversation_mode": "ask",
            }
        }
    )
    try:
        observed.append(
            json.loads(await ask.ainvoke({"expert": "child", "message": "Report today's traffic"}))
        )
        if mode == "async":
            await asyncio.wait_for(harness.inbox._queue.join(), 3)
            await asyncio.gather(*list(harness.inbox._tasks.values()), return_exceptions=True)
        items = rig.collaboration.listing(rig.owner, "parent", "root", 0, 100)
        assert len(items["invocations"]) == (2 if scenario == "nested" else 1)
        item = next(item for item in items["invocations"] if item["source_agent_id"] == "parent")
        assert item["task_outcome"] == expected, item
        expected_transport = (
            "failed"
            if scenario == "abnormal"
            else "running"
            if scenario == "terminal_conflict"
            else "completed"
        )
        assert item["transport_status"] == expected_transport, item
        if scenario == "terminal_conflict":
            receipt = (
                observed[0].get("dispatch_receipt")
                if mode == "sync"
                else harness._dispatch_claims[item["invocation_id"]][1].result().receipt.to_dict()
            )
            assert receipt["transport_status"] == "unknown", receipt
            assert receipt["task_outcome"] == "unknown", receipt
        assert not items["artifacts"]
        assert "pending_task_result" not in item and "ready_task_result" not in item
        if expected != "unknown":
            assert item["task_result"]["provenance"] == "expert_reported"
            assert item["task_result"]["summary"] == "Public task summary"
            assert item["reply_received"] is True
        else:
            assert "task_result" not in item
        assert sum(e["event_type"] == "delegation.result_reported" for e in items["events"]) == (
            2 if scenario == "nested" else scenario not in {"none", "availability_failure"}
        )
    finally:
        var_child_runnable_config.reset(scope)
        await harness.inbox.shutdown()


@pytest.mark.asyncio
async def test_report_runtime_binding_and_validation(rig: Any) -> None:
    from octop_harness.teams import DispatchReceipt

    peer = call(rig)
    rig.collaboration.accept(peer)
    rig.collaboration.bind(peer, "child-thread", {"octop_child_bound": True})
    await rig.collaboration.lifecycle(
        peer, DispatchReceipt(invocation_id="inv-1", transport_status="running")
    )
    svc = TaskResultService(rig.manager)
    cfg = {
        "user": rig.owner,
        "thread_id": "child-thread",
        "octop_child_bound": True,
        "octop_invocation_id": "inv-1",
    }
    for changed in (
        {"user": rig.outsider},
        {"thread_id": "unrelated"},
        {"octop_child_bound": False},
        {"octop_invocation_id": "fake"},
    ):
        with pytest.raises(OctopError):
            svc.report(
                "child", {**cfg, **changed}, TaskResultInput(outcome="succeeded", summary="Done")
            )
    for summary in ("   ", "<think>private</think>"):
        with pytest.raises(ValueError):
            svc.report("child", cfg, TaskResultInput(outcome="succeeded", summary=summary))
    with pytest.raises(ValueError):
        svc.report(
            "child",
            cfg,
            TaskResultInput(outcome="succeeded", summary="Done", resource_ids=["same", "same"]),
        )
    with pytest.raises(OctopError):
        svc.report(
            "child",
            cfg,
            TaskResultInput(outcome="succeeded", summary="Done", resource_ids=["not-produced"]),
        )


@pytest.mark.asyncio
async def test_real_published_evidence_and_granted_resource_rejection(rig: Any) -> None:
    from octop_harness.teams import DispatchReceipt

    peer = call(rig)
    rig.collaboration.accept(peer)
    rig.collaboration.bind(peer, "child-thread", {"octop_child_bound": True})
    await rig.collaboration.lifecycle(
        peer, DispatchReceipt(invocation_id="inv-1", transport_status="running")
    )
    cfg = {
        "user": rig.owner,
        "thread_id": "child-thread",
        "octop_child_bound": True,
        "octop_invocation_id": "inv-1",
    }
    rig.workspaces["child"].files["generated/result.md"] = b"Public evidence"
    token = var_child_runnable_config.set({"configurable": cfg})
    try:
        published = await rig.resources.publish(
            rig.owner, "child", "child-thread", "generated/result.md"
        )
    finally:
        var_child_runnable_config.reset(token)
    assert published["producer_invocation_id"] == "inv-1"
    service = TaskResultService(rig.manager)
    granted = await rig.resources.register(rig.owner, "parent", "inbound/paper.txt", thread="root")
    with pytest.raises(OctopError):
        service.report(
            "child",
            cfg,
            TaskResultInput(
                outcome="succeeded", summary="Done", resource_ids=[granted["resource_id"]]
            ),
        )
    result = service.report(
        "child",
        cfg,
        TaskResultInput(
            outcome="succeeded", summary="Done", resource_ids=[published["resource_id"]]
        ),
    )
    assert result["status"] == "pending"
    stored = rig.repos.collaboration_repo.get("collaboration_invocations", rig.owner, "inv-1")
    assert stored["pending_task_result"]["resources"] == [
        {"resource_id": published["resource_id"], "version": published["version"]}
    ]
    assert stored["task_outcome"] == "unknown"


def test_report_is_read_only_telemetry_in_ask_and_plan() -> None:
    from octop.infra.agents.conversation_mode import HOST_READ_TOOLS

    assert "report_task_result" in HOST_READ_TOOLS
    assert "deliver_resource" not in HOST_READ_TOOLS
    assert "execute" not in HOST_READ_TOOLS


@pytest.mark.asyncio
async def test_old_final_before_invocation_and_conflicting_candidate_cas_cannot_commit(
    rig: Any, monkeypatch: Any
) -> None:
    from octop_harness.teams import DispatchReceipt

    rig.repos.thread_message_repo.append_if_ready(
        "child-thread", message_inputs([AIMessage(content="Old reply", id="old-final")])
    )
    peer = call(rig)
    rig.collaboration.accept(peer)
    rig.collaboration.bind(peer, "child-thread", {"octop_child_bound": True})
    await rig.collaboration.lifecycle(
        peer, DispatchReceipt(invocation_id="inv-1", transport_status="running")
    )
    cfg = {
        "user": rig.owner,
        "thread_id": "child-thread",
        "octop_child_bound": True,
        "octop_invocation_id": "inv-1",
    }
    service = TaskResultService(rig.manager)
    original = rig.repos.collaboration_repo.save
    monkeypatch.setattr(rig.repos.collaboration_repo, "save", lambda *a, **k: False)
    with pytest.raises(ValueError, match="TASK_RESULT_CONFLICT"):
        service.report("child", cfg, TaskResultInput(outcome="succeeded", summary="Done"))
    monkeypatch.setattr(rig.repos.collaboration_repo, "save", original)
    service.report("child", cfg, TaskResultInput(outcome="succeeded", summary="Done"))
    result = {
        "messages": [AIMessage(content="Old reply", id="old-final")],
        "dispatch_receipt": {"task_outcome": "succeeded"},
    }
    service.prepare_result(peer, "child-thread", result)
    assert "dispatch_receipt" not in result
    await rig.collaboration.lifecycle(
        peer,
        DispatchReceipt(
            invocation_id="inv-1", transport_status="completed", task_outcome="succeeded"
        ),
    )
    saved = rig.repos.collaboration_repo.get("collaboration_invocations", rig.owner, "inv-1")
    assert saved["task_outcome"] == "unknown"
    assert saved["task_result_reason"] == "TASK_RESULT_EVIDENCE_MISSING"
    assert rig.collaboration.public(saved, rig.owner)["reply_received"] is False


@pytest.mark.asyncio
async def test_reply_inspection_missing_child_and_intermediate_before_toolcall(rig: Any) -> None:
    from octop_harness.teams import DispatchReceipt

    peer = call(rig)
    rig.collaboration.accept(peer)
    rig.collaboration.bind(peer, "child-thread", {})
    rig.repos.thread_message_repo.append_if_ready(
        "child-thread",
        message_inputs(
            [
                AIMessage(content="Intermediate", id="intermediate"),
                AIMessage(
                    content="Working",
                    id="tool-calling",
                    tool_calls=[{"name": "read_file", "args": {}, "id": "tool"}],
                ),
            ]
        ),
    )
    await rig.collaboration.lifecycle(
        peer, DispatchReceipt(invocation_id="inv-1", transport_status="running")
    )
    await rig.collaboration.lifecycle(
        peer, DispatchReceipt(invocation_id="inv-1", transport_status="completed")
    )
    assert (
        rig.collaboration.listing(rig.owner, "parent", "root", 0, 100)["invocations"][0][
            "reply_received"
        ]
        is False
    )
    with rig.repos.db.transaction() as conn:
        conn.execute("DELETE FROM threads WHERE thread_id=?", ("child-thread",))
    assert (
        rig.collaboration.listing(rig.owner, "parent", "root", 0, 100)["invocations"][0][
            "reply_received"
        ]
        is False
    )
