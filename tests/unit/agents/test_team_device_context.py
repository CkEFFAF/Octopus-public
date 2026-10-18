"""Canonical Harness middleware drives application context and durable lifecycle."""

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
from octop_harness.teams import DispatchOptions, DispatchReceipt
from octop_harness.teams.team_manager import TeamManager as HarnessTeam
from tests.unit.agents.test_collaboration_resources import call
from tests.unit.agents.test_collaboration_resources import rig as rig

from octop.infra.agents.teams.team_manager import TeamManager
from octop.infra.gateway.threads import ThreadRegistry


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    "policy,expected",
    [("inherit", "gpu"), ("member_default", "laptop"), ("explicit", "explicit-pc")],
)
async def test_real_middleware_app_prepare_lifecycle_target_and_resource(
    rig: Any, mode: str, policy: str, expected: str
) -> None:
    resource = await rig.resources.register(rig.owner, "parent", "inbound/paper.txt", thread="root")
    requests = []
    finished = asyncio.Event()

    async def child(request: Any) -> dict[str, Any]:
        requests.append(request)
        cfg = request.configurable
        persisted = rig.collaboration.repo.get(
            "collaboration_invocations", rig.owner, cfg["octop_invocation_id"]
        )
        assert persisted["transport_status"] == "running"
        assert persisted["resolved_target"]["device_id"] == ids[expected]
        assert cfg["conversation_mode"] == "ask"
        assert cfg["octop_execution_context"]["work_mode"] == "ask"
        text = await rig.resources.read(
            rig.owner,
            "child",
            request.thread_id,
            resource_id=resource["resource_id"],
            invocation_id=cfg["octop_invocation_id"],
        )
        assert text["text"] == "A paper with source text."
        finished.set()
        return {"messages": [AIMessage(content="Read paper", id="answer")]}

    entries = {
        aid: SimpleNamespace(
            agent_id=aid,
            config=SimpleNamespace(name=aid, team_peers=None, peer_invoke_mode=None),
            metadata={"user_id": rig.owner, "name": aid},
            agent=SimpleNamespace(
                call=child
                if aid == "child"
                else AsyncMock(return_value={"messages": [AIMessage(content="Followup")]})
            ),
        )
        for aid in ("parent", "child")
    }
    registry = MagicMock()
    registry.get.side_effect = entries.__getitem__
    registry.list.return_value = list(entries.values())
    harness = HarnessTeam(registry)
    harness.set_processor(
        SimpleNamespace(compose_followup=lambda *a, **k: "Done", on_reply=AsyncMock())
    )
    rig.manager._harness_manager = SimpleNamespace(team=harness)
    rig.manager.get_row = lambda aid: rig.repos.agent_repo.get(aid)
    rig.manager._team_jobs = None

    from octop.infra.agents.manager import AgentManager
    from octop.infra.devices.service import DeviceService
    from octop.infra.execution.service import ExecutionService

    devices = DeviceService(rig.repos, local_state_dir=rig.manager.paths.root / "native")
    ids = {
        name: devices.enroll(
            owner_user_id=rig.owner,
            name=name,
            platform="linux",
            capabilities=["files_read"],
            permissions=["files_read"],
            roots=[],
            trust_mode="restricted",
        )["device"]["device_id"]
        for name in ("gpu", "laptop", "explicit-pc")
    }
    rig.repos.agent_repo.update_config(
        "child", config_json=json.dumps({"device_binding": {"device_id": ids["laptop"]}})
    )
    actual = AgentManager(repos=rig.repos, paths=rig.manager.paths)
    actual._device_service = devices
    rig.manager._device_service = devices
    rig.manager._prepare_stream_request = actual._prepare_stream_request
    parent_context = ExecutionService(devices).resolve(
        rig.owner,
        agent_id="parent",
        thread_id="root",
        device_id=ids["gpu"],
        work_mode="ask",
        run_id="root-run",
    )
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
    ask = next(
        tool
        for tool in PeerAgentMiddleware(harness, peer_invoke_mode=mode).tools
        if tool.name == "ask_agent"
    )
    cfg = {
        "user": str(rig.owner),
        "agent_id": "parent",
        "thread_id": "root",
        "session_key": "parent:dashboard:1:dm",
        "conversation_mode": "ask",
        "octop_task_run_id": "root-run",
        "octop_device_target": {
            "device_id": ids["gpu"],
            "grant_version": parent_context.grant_version,
        },
        "octop_execution_context": parent_context.public(),
    }
    token = var_child_runnable_config.set({"configurable": cfg})
    try:
        args = {
            "expert": "child",
            "message": "Read this paper",
            "target_policy": policy,
            "resource_ids": [resource["resource_id"]],
        }
        if policy == "explicit":
            args["device_id"] = ids["explicit-pc"]
        result = json.loads(await ask.ainvoke(args))
        assert "error" not in result, result
        await asyncio.wait_for(finished.wait(), 2)
        if mode == "async":
            await asyncio.wait_for(harness.inbox._queue.join(), 2)
            await asyncio.gather(*list(harness.inbox._tasks.values()), return_exceptions=True)
        assert result["dispatch_receipt"]["invocation_id"]
        rows = rig.collaboration.listing(rig.owner, "parent", "root", 0, 100)["invocations"]
        assert len(rows) == 1 and rows[0]["transport_status"] == "completed"
        assert rows[0]["task_outcome"] == "unknown"
        assert rows[0]["child_thread_id"] != "root"
        assert cfg["octop_execution_context"]["context_id"] == parent_context.context_id
    finally:
        var_child_runnable_config.reset(token)
        await harness.inbox.shutdown()
        await devices.shutdown()


@pytest.mark.asyncio
async def test_durable_replay_conflict_unknown_and_retry_are_separate(rig: Any) -> None:
    peer = call(rig)
    receipt = DispatchReceipt(invocation_id=peer.invocation_id)
    assert await rig.collaboration.lifecycle(peer, receipt) is None
    replay = await rig.collaboration.lifecycle(peer, receipt)
    assert replay.transport_status == "accepted"
    conflict = call(rig, message="Different task")
    with pytest.raises(ValueError, match="INVOCATION_CONFLICT"):
        await rig.collaboration.lifecycle(conflict, receipt)
    rig.collaboration.reconcile_startup()
    prior = rig.collaboration.repo.get("collaboration_invocations", rig.owner, "inv-1")
    assert prior["transport_status"] == "unknown"
    retry = call(rig, identity="inv-2", retry_of="inv-1")
    assert await rig.collaboration.lifecycle(retry, DispatchReceipt(invocation_id="inv-2")) is None
    assert rig.collaboration.accept(retry)["retry_of"] == "inv-1"
    events = rig.collaboration.listing(rig.owner, "parent", "root", 0, 100)["events"]
    assert len({event["event_id"] for event in events}) == len(events)
    first = rig.collaboration.listing(rig.owner, "parent", "root", 0, 1)
    second = rig.collaboration.listing(rig.owner, "parent", "root", first["next_cursor"], 100)
    assert all(event["seq"] > first["next_cursor"] for event in second["events"])


@pytest.mark.asyncio
async def test_same_callee_overlap_replay_and_cancellation_keep_separate_attempts(rig: Any) -> None:

    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def child(request):
        calls.append(request)
        if len(calls) >= 2:
            entered.set()
        await release.wait()
        return {"messages": [AIMessage(content="Finished", id="a:" + request.thread_id)]}

    entries = {
        aid: SimpleNamespace(
            agent_id=aid,
            config=SimpleNamespace(name=aid, team_peers=None, peer_invoke_mode=None),
            metadata={"user_id": rig.owner, "name": aid},
            agent=SimpleNamespace(call=child),
        )
        for aid in ("parent", "child")
    }
    registry = MagicMock()
    registry.get.side_effect = entries.__getitem__
    registry.list.return_value = list(entries.values())
    harness = HarnessTeam(registry)
    harness.set_processor(
        SimpleNamespace(compose_followup=lambda *a, **k: "Done", on_reply=AsyncMock())
    )
    rig.manager._harness_manager = SimpleNamespace(team=harness)
    rig.manager.get_row = rig.repos.agent_repo.get
    rig.manager._prepare_stream_request = lambda aid, request: request
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
    token = var_child_runnable_config.set(
        {
            "configurable": {
                "user": rig.owner,
                "agent_id": "parent",
                "thread_id": "root",
                "octop_task_run_id": "root-run",
            }
        }
    )
    tasks = []
    try:
        kwargs = {
            "from_agent_id": "parent",
            "to_agent_id": "child",
            "message": "Work",
            "user_id": rig.owner,
            "source_thread_id": "root",
            "session_key": "parent:dashboard:1:dm",
            "dispatch_options": DispatchOptions(),
        }
        tasks = [
            asyncio.create_task(harness.call_peer(**kwargs, invocation_key=key))
            for key in ("call-one", "call-two")
        ]
        await asyncio.wait_for(entered.wait(), 2)
        records = rig.collaboration.listing(rig.owner, "parent", "root", 0, 100)["invocations"]
        assert len({record["child_thread_id"] for record in records}) == 2
        assert len({request.configurable["octop_invocation_id"] for request in calls}) == 2
        cancelled = records[0]["invocation_id"]
        await harness.acancel_peer(cancelled)
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        records = rig.collaboration.listing(rig.owner, "parent", "root", 0, 100)["invocations"]
        assert {record["transport_status"] for record in records} == {"unknown", "completed"}
        completed = next(record for record in records if record["transport_status"] == "completed")
        await harness.acancel_peer(completed["invocation_id"])
        late = rig.collaboration.repo.get(
            "collaboration_invocations", rig.owner, completed["invocation_id"]
        )
        assert late["transport_status"] == "completed" and late["cancel_too_late"] is True
        before = len(calls)
        await harness.call_peer(**kwargs, invocation_key="call-two")
        assert len(calls) == before
        events = rig.collaboration.listing(rig.owner, "parent", "root", 0, 100)["events"]
        assert (
            len(
                [
                    event
                    for event in events
                    if event["event_type"]
                    in {"delegation.cancel_requested", "delegation.cancel_too_late"}
                ]
            )
            == 2
        )
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await harness.inbox.shutdown()
        var_child_runnable_config.reset(token)


@pytest.mark.asyncio
async def test_completion_wins_requested_cancel_atomically_and_replay_is_idempotent(
    rig: Any,
) -> None:
    from dataclasses import replace

    peer = call(rig)
    accepted = DispatchReceipt(invocation_id=peer.invocation_id)
    await rig.collaboration.lifecycle(peer, accepted)
    await rig.collaboration.lifecycle(peer, replace(accepted, transport_status="running"))
    rig.collaboration.request_cancel(rig.owner, peer.invocation_id)
    await rig.collaboration.lifecycle(peer, replace(accepted, transport_status="completed"))
    await rig.collaboration.lifecycle(peer, replace(accepted, transport_status="completed"))
    item = rig.collaboration.repo.get("collaboration_invocations", rig.owner, peer.invocation_id)
    assert item["transport_status"] == "completed" and item["cancel_too_late"] is True
    events = rig.collaboration.listing(rig.owner, "parent", "root", 0, 100)["events"]
    names = [event["event_type"] for event in events]
    assert names.count("delegation.cancel_requested") == 1
    assert names.count("delegation.cancel_too_late") == 1
    assert names.count("delegation.completed") == 1
    assert "delegation.cancelled" not in names
