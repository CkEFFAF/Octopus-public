"""Real Harness inbox dispatch preserves device target and task lifetime."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage
from langgraph.config import var_child_runnable_config
from octop_harness.teams.team_manager import TeamManager as HarnessTeam

from octop.infra.agents.teams.device_context import PeerTaskTracker
from octop.infra.agents.teams.team_manager import _chat_request_payload, wire_host_dispatch
from octop.infra.errors import OctopError


@pytest.fixture
def peers() -> Any:
    requests: list[dict[str, Any]] = []
    started, release, following, finish = (asyncio.Event() for _ in range(4))
    device = SimpleNamespace(grant_version=7)
    devices = SimpleNamespace(owned=MagicMock(return_value=device))
    on_followup = AsyncMock()

    async def member(request: Any, **_: Any) -> Any:
        requests.append(_chat_request_payload(request, "member"))
        started.set()
        await release.wait()
        return {"messages": [AIMessage(content="Member finished")]}

    async def host(request: Any, **_: Any) -> Any:
        requests.append(_chat_request_payload(request, "host"))
        await on_followup()
        following.set()
        await finish.wait()
        return {"messages": [AIMessage(content="Host finished")]}

    entries = {
        aid: SimpleNamespace(
            agent_id=aid,
            config=SimpleNamespace(name=aid),
            metadata={"user_id": 1, "name": aid},
            agent=SimpleNamespace(
                call=AsyncMock(return_value={"messages": [AIMessage(content="OK")]})
            ),
        )
        for aid in ("host", "member")
    }
    registry = MagicMock()
    registry.get.side_effect = entries.__getitem__
    team = HarnessTeam(registry)
    processor = SimpleNamespace(compose_followup=lambda *a, **k: "Follow up", on_reply=AsyncMock())
    team.set_processor(processor)

    async def enrich(_agent: str, request: Any) -> Any:
        # A callee default must not weaken the caller's consent.
        request.conversation_mode = "craft"
        request.agent_id = _agent
        request.mcp_use_default = True
        return request

    team.bind_invocation_hooks(enrich_request=enrich)
    wire_host_dispatch(
        team, is_team=lambda aid: aid == "host", stream_peer=member, stream_host=host
    )
    tracker = PeerTaskTracker(devices)
    tracker.install(team)
    return SimpleNamespace(
        team=team,
        tracker=tracker,
        requests=requests,
        device=device,
        started=started,
        release=release,
        following=following,
        finish=finish,
        entries=entries,
        on_followup=on_followup,
    )


def dispatch(rig: Any, mode: str = "craft") -> Any:
    token = var_child_runnable_config.set(
        {
            "configurable": {
                "user": "1",
                "conversation_mode": mode,
                "octop_task_run_id": "run-a",
                "octop_device_target": {"device_id": "pc", "grant_version": 7},
                "skills": [],
                "mcp_servers": [],
                "hitl_policy": {"mode": "allow_all"},
            }
        }
    )
    try:
        return rig.team.submit_peer(
            from_agent_id="host",
            to_agent_id="member",
            user_id=1,
            message="Do work",
            source_thread_id="room",
            metadata={"session_key": "host:dashboard:1"},
        )
    finally:
        var_child_runnable_config.reset(token)


async def close(rig: Any) -> None:
    inbox = rig.team.inbox
    tasks = [task for task in [inbox._worker, *inbox._tasks.values()] if task is not None]
    inbox.cancel_worker()
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["craft", "ask", "plan"])
async def test_async_member_and_followup_keep_snapshot_and_hold_task(peers: Any, mode: str) -> None:
    rig = peers
    try:
        dispatch(rig, mode)
        waiting = asyncio.create_task(rig.tracker.wait_for_task_run(1, "run-a"))
        await asyncio.wait_for(rig.started.wait(), 2)
        assert not waiting.done()
        rig.release.set()
        await asyncio.wait_for(rig.following.wait(), 2)
        assert not waiting.done()
        for request in rig.requests:
            cfg = request["configurable"]
            assert cfg["octop_device_target"] == {"device_id": "pc", "grant_version": 7}
            assert cfg["octop_task_run_id"] == "run-a"
            assert request["conversation_mode"] == mode
            assert request["skills"] == request["mcp_servers"] == []
            assert "hitl_policy" not in cfg
        rig.finish.set()
        await asyncio.wait_for(waiting, 2)
    finally:
        await close(rig)


@pytest.mark.asyncio
async def test_cancel_queued_member_never_enters_agent(peers: Any) -> None:
    rig = peers
    try:
        dispatch(rig)
        await rig.tracker.cancel_task_run(1, "run-a")
        with pytest.raises(OctopError):
            await rig.tracker.wait_for_task_run(1, "run-a")
        with pytest.raises(OctopError):
            dispatch(rig)
        await asyncio.sleep(0.05)
        assert rig.requests == []
    finally:
        await close(rig)


@pytest.mark.asyncio
async def test_changed_grant_blocks_old_queued_snapshot(peers: Any) -> None:
    rig = peers
    try:
        dispatch(rig)
        rig.device.grant_version = 8
        with pytest.raises(OctopError):
            await asyncio.wait_for(rig.tracker.wait_for_task_run(1, "run-a"), 2)
        assert rig.requests == []
    finally:
        await close(rig)


@pytest.mark.asyncio
async def test_sync_member_inherits_device_without_identity_override(peers: Any) -> None:
    rig = peers
    token = var_child_runnable_config.set(
        {
            "configurable": {
                "user": "1",
                "conversation_mode": "ask",
                "octop_device_target": {"device_id": "pc", "grant_version": 7},
            }
        }
    )
    try:
        await rig.team.call_peer(
            from_agent_id="member", to_agent_id="host", user_id=1, message="Read"
        )
        request = rig.entries["host"].agent.call.call_args.args[0]
        assert request.user == "1" and request.agent_id == "host"
        assert request.conversation_mode == "ask"
        assert request.mcp_servers == request.skills == []
        assert request.configurable["octop_device_target"]["grant_version"] == 7
    finally:
        var_child_runnable_config.reset(token)
        await close(rig)


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery_fails", [False, True])
async def test_parent_can_integrate_actual_child_receipt_before_delivery_finishes(
    peers: Any, tmp_path: Any, delivery_fails: bool
) -> None:
    from octop.infra.db.migrate import run_migrations
    from octop.infra.db.pool import SqlitePool
    from octop.infra.db.services import RepoBundle
    from octop.infra.execution.work_mode import WorkModeService

    rig = peers
    db = SqlitePool(tmp_path / "team.db")
    run_migrations(db)
    repos = RepoBundle.from_pool(db)
    owner = repos.user_repo.create(username="owner", password_hash="unused", role="admin")
    assert owner == 1
    repos.agent_repo.create(agent_id="host", user_id=owner, name="Host")
    repos.thread_repo.insert(
        thread_id="room",
        user_id=owner,
        agent_id="host",
        channel_type="dashboard",
        session_key="work",
    )
    rig.tracker.devices.repos = repos
    modes = WorkModeService(repos)
    cfg = {"thread_id": "room", "octop_task_run_id": "run-a", "work_mode": "team"}

    def advance(stage: str, evidence: list[str]) -> Any:
        version = modes.begin(owner, "host", cfg)["payload"]["version"]
        return modes.step(
            owner,
            "host",
            cfg,
            version=version,
            stage=stage,
            status="completed",
            report="Observed peer result",
            evidence_ids=evidence,
        )

    advance("decompose", [])

    async def integrate() -> None:
        receipts = modes.events.list(owner, "host", "room", run_id="run-a")
        completed = [
            item["event_id"]
            for item in receipts
            if item["kind"] == "dispatch" and item["status"] == "completed"
        ]
        assert len(completed) == 1
        if modes.begin(owner, "host", cfg)["status"] != "completed":
            advance("dispatch", completed)
            assert advance("integrate", completed)["status"] == "completed"
        if delivery_fails:
            raise RuntimeError("parent delivery unavailable")

    rig.on_followup.side_effect = integrate
    try:
        dispatch(rig)
        await asyncio.wait_for(rig.started.wait(), 2)
        rig.release.set()
        rig.finish.set()
        waiting = rig.tracker.wait_for_task_run(owner, "run-a")
        if delivery_fails:
            with pytest.raises(OctopError):
                await asyncio.wait_for(waiting, 2)
        else:
            await asyncio.wait_for(waiting, 2)
        assert rig.on_followup.await_count >= 1
        receipts = modes.events.list(owner, "host", "room", run_id="run-a")
        assert [item["status"] for item in receipts if item["kind"] == "dispatch"] == ["completed"]
    finally:
        await close(rig)
        db.close()
