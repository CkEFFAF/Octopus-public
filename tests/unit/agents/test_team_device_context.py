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
    on_member = AsyncMock(return_value={"messages": [AIMessage(content="Member finished")]})

    async def member(request: Any, **_: Any) -> Any:
        requests.append(_chat_request_payload(request, "member"))
        started.set()
        await release.wait()
        return await on_member(request)

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
        on_member=on_member,
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
        # This checks receipt ordering, not wall-clock speed. Parallel Windows
        # CI can spend more than two seconds committing the SQLite transitions.
        if delivery_fails:
            with pytest.raises(OctopError):
                await asyncio.wait_for(waiting, 10)
        else:
            await asyncio.wait_for(waiting, 10)
        assert rig.on_followup.await_count >= 1
        receipts = modes.events.list(owner, "host", "room", run_id="run-a")
        assert [item["status"] for item in receipts if item["kind"] == "dispatch"] == ["completed"]
    finally:
        await close(rig)
        db.close()


@pytest.mark.asyncio
async def test_member_work_step_uses_in_run_device_evidence_after_ask_agent(
    peers: Any, tmp_path: Any
) -> None:
    """Parent team ask_agent child can complete execute→verify with device evidence.

    Reproduces cloud failure: member GPU command succeeded, but verify raised
    ``evidence must belong to this run`` (bare operation id / work_step id),
    and the host dispatch receipt flipped to failed while work was still useful.
    """
    from octop.infra.db.migrate import run_migrations
    from octop.infra.db.pool import SqlitePool
    from octop.infra.db.services import RepoBundle
    from octop.infra.execution.work_mode import WorkModeService

    rig = peers
    db = SqlitePool(tmp_path / "peer-evidence.db")
    run_migrations(db)
    repos = RepoBundle.from_pool(db)
    owner = repos.user_repo.create(username="owner", password_hash="unused", role="admin")
    assert owner == 1
    repos.agent_repo.create(agent_id="host", user_id=owner, name="Host")
    repos.agent_repo.create(agent_id="member", user_id=owner, name="Member")
    repos.thread_repo.insert(
        thread_id="room",
        user_id=owner,
        agent_id="host",
        channel_type="dashboard",
        session_key="work",
    )
    peer_thread = "room~member"
    repos.thread_repo.insert(
        thread_id=peer_thread,
        user_id=owner,
        agent_id="member",
        channel_type="dashboard",
        session_key="peer:work",
    )
    rig.tracker.devices.repos = repos
    modes = WorkModeService(repos)

    # Host run id shared with the member via PeerTaskTracker snapshot.
    host_cfg = {"thread_id": "room", "octop_task_run_id": "run-a", "work_mode": "team"}
    modes.begin(owner, "host", host_cfg)

    result = dispatch(rig)
    assert result.job_id
    await asyncio.wait_for(rig.started.wait(), 2)

    # While the member is still running, dispatch receipt must stay accepted.
    mid = modes.events.get(owner, f"dispatch:{result.job_id}")
    assert mid is not None
    assert mid["status"] == "accepted"
    assert mid["run_id"] == "run-a"

    # Member workflow + completed device evidence on the shared run.
    member_cfg = {
        "thread_id": peer_thread,
        "octop_task_run_id": "run-a",
        "work_mode": "agentic",
        "user": owner,
    }
    modes.begin(owner, "member", member_cfg)
    op = "01PEERDEVICEOP000000000000"
    modes.events.save(
        event_id=f"operation:{op}",
        owner=owner,
        agent_id="member",
        thread_id=peer_thread,
        run_id="run-a",
        context_id=None,
        kind="device",
        status="completed",
        payload={"operation_id": op, "action": "command.run", "name": "device_run"},
    )
    # Model pasted bare operation_id (common) for execute, then canonical id for verify.
    version = modes.begin(owner, "member", member_cfg)["payload"]["version"]
    modes.step(
        owner,
        "member",
        member_cfg,
        version=version,
        stage="execute",
        status="completed",
        report="Ran GPU probe on bound device",
        evidence_ids=[op],
    )
    version = modes.begin(owner, "member", member_cfg)["payload"]["version"]
    done = modes.step(
        owner,
        "member",
        member_cfg,
        version=version,
        stage="verify",
        status="completed",
        report="Confirmed command receipt",
        evidence_ids=[f"operation:{op}"],
    )
    assert done["status"] == "completed"

    # Still accepted until the inbox observer finalizes.
    assert modes.events.get(owner, f"dispatch:{result.job_id}")["status"] == "accepted"

    rig.release.set()
    await asyncio.wait_for(rig.following.wait(), 2)
    rig.finish.set()
    await asyncio.wait_for(rig.tracker.wait_for_task_run(1, "run-a"), 2)
    assert modes.events.get(owner, f"dispatch:{result.job_id}")["status"] == "completed"
    await close(rig)


@pytest.mark.asyncio
async def test_member_default_target_policy_strips_parent_device(peers: Any) -> None:
    """0019 S4: target_policy=member_default must not inherit host device."""
    from octop.infra.agents.teams.device_context import _KEY

    rig = peers
    token = var_child_runnable_config.set(
        {
            "configurable": {
                "user": "1",
                "conversation_mode": "craft",
                "octop_task_run_id": "run-b",
                "octop_device_target": {"device_id": "pc", "grant_version": 7},
                "octop_target_policy": "member_default",
            }
        }
    )
    try:
        result = rig.team.submit_peer(
            from_agent_id="host",
            to_agent_id="member",
            user_id=1,
            message="Use my default",
            source_thread_id="room",
            metadata={"session_key": "host:dashboard:1"},
        )
        assert result.job_id
        msg = rig.team.inbox.get(result.job_id)
        assert msg is not None
        snap = msg.metadata[_KEY]
        cfg = snap["configurable"]
        assert "octop_device_target" not in cfg
        assert "octop_execution_context" not in cfg
        assert cfg.get("octop_target_policy") == "member_default"
        # Cancel so the inbox worker does not need a full member turn.
        await rig.tracker.cancel_task_run(1, "run-b")
    finally:
        var_child_runnable_config.reset(token)
        await close(rig)


@pytest.mark.asyncio
async def test_ask_agent_member_recovers_with_real_callback_receipt(
    peers: Any, tmp_path: Any
) -> None:
    """Exercise inbox context → member graph → callback sink → work_step retry."""
    from deepagents import create_deep_agent
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import HumanMessage, ToolMessage
    from langchain_core.tools import tool
    from octop_harness.observability.run_events import RunEventCallback

    from octop.infra.agents.middleware.work_mode import WorkModeMiddleware
    from octop.infra.db.migrate import run_migrations
    from octop.infra.db.pool import SqlitePool
    from octop.infra.db.services import RepoBundle
    from octop.infra.execution.events import RunInspectionService
    from octop.infra.execution.work_mode import WorkModeService, build_work_mode_tools

    class Model(FakeMessagesListChatModel):
        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
            return self

    @tool
    def device_run(command: str) -> str:
        """Probe a device (the transport boundary is stubbed in this regression)."""
        return "GPU available"

    rig = peers
    db = SqlitePool(tmp_path / "member-callback.db")
    run_migrations(db)
    repos = RepoBundle.from_pool(db)
    owner = repos.user_repo.create(username="owner", password_hash="unused", role="admin")
    for agent in ("host", "member"):
        repos.agent_repo.create(agent_id=agent, user_id=owner, name=agent)
    repos.thread_repo.insert(
        thread_id="room",
        user_id=owner,
        agent_id="host",
        channel_type="dashboard",
        session_key="work",
    )
    rig.tracker.devices.repos = repos
    service = WorkModeService(repos)
    member_states: list[Any] = []

    async def run_member(request: Any) -> Any:
        payload = _chat_request_payload(request, "member")
        cfg = {
            **payload["configurable"],
            "thread_id": payload["thread_id"],
            "user": payload["user"],
            "work_mode": "agentic",
        }
        assert cfg["octop_task_run_id"] == "run-a"
        repos.thread_repo.insert(
            thread_id=cfg["thread_id"],
            user_id=owner,
            agent_id="member",
            channel_type="dashboard",
            session_key="peer:work",
        )
        model = Model(
            responses=[
                AIMessage(
                    "",
                    tool_calls=[
                        {"id": "call_gpu", "name": "device_run", "args": {"command": "probe"}}
                    ],
                ),
                AIMessage(
                    "",
                    tool_calls=[
                        {
                            "id": "call_bad_step",
                            "name": "work_step",
                            "args": {
                                "stage": "execute",
                                "status": "completed",
                                "report": "GPU observed",
                                "evidence_ids": ["call_bad_step"],
                            },
                        }
                    ],
                ),
                AIMessage(
                    "",
                    tool_calls=[
                        {
                            "id": "call_retry",
                            "name": "work_step",
                            "args": {
                                "stage": "execute",
                                "status": "completed",
                                "report": "GPU observed",
                                "evidence_ids": ["call_gpu"],
                            },
                        }
                    ],
                ),
                AIMessage(
                    "",
                    tool_calls=[
                        {
                            "id": "call_verify",
                            "name": "work_step",
                            "args": {
                                "stage": "verify",
                                "version": 1,
                                "status": "completed",
                                "report": "Receipt verified",
                                "evidence_ids": ["tool:call_gpu"],
                            },
                        }
                    ],
                ),
                AIMessage("Member verified"),
            ]
        )
        callback = RunEventCallback(
            lambda event: RunInspectionService(repos).tool_receipt("member", event)
        )
        graph = create_deep_agent(
            model=model,
            tools=[device_run, *build_work_mode_tools(service, "member")],
            middleware=[WorkModeMiddleware(service, "member")],
        )
        result = await graph.ainvoke(
            {"messages": [HumanMessage("Probe GPU")]},
            config={"configurable": cfg, "callbacks": [callback]},
        )
        failed = next(
            item
            for item in result["messages"]
            if isinstance(item, ToolMessage) and item.tool_call_id == "call_bad_step"
        )
        assert failed.status == "error"
        state = service.begin(owner, "member", cfg)
        assert state["status"] == "completed"
        gpu = next(
            item
            for item in service.events.list(owner, "member", cfg["thread_id"], run_id="run-a")
            if item["payload"].get("tool_call_id") == "call_gpu"
        )
        assert gpu["event_id"] != "tool:call_gpu"
        assert all(
            stage["evidence_ids"] == [gpu["event_id"]] for stage in state["payload"]["stages"]
        )
        member_states.append(state)
        return result

    rig.on_member.side_effect = run_member
    try:
        result = dispatch(rig)
        await asyncio.wait_for(rig.started.wait(), 10)
        assert service.events.get(owner, f"dispatch:{result.job_id}")["status"] == "accepted"
        rig.release.set()
        rig.finish.set()
        await asyncio.wait_for(rig.tracker.wait_for_task_run(owner, "run-a"), 30)
        assert len(member_states) == 1
        assert service.events.get(owner, f"dispatch:{result.job_id}")["status"] == "completed"
    finally:
        await close(rig)
        db.close()


@pytest.mark.asyncio
async def test_pending_ask_target_policy_reaches_submit_peer_snapshot(peers: Any) -> None:
    """ask_agent ContextVar stamp must reach PeerTaskTracker without mutating shared cfg."""
    from octop.infra.agents.teams import target_visibility as tv
    from octop.infra.agents.teams.device_context import _KEY

    rig = peers
    shared = {
        "user": "1",
        "conversation_mode": "craft",
        "octop_task_run_id": "run-c",
        "octop_device_target": {"device_id": "pc", "grant_version": 7},
    }
    token = var_child_runnable_config.set({"configurable": shared})
    pending = tv._PENDING_ASK_TARGET.set(
        {
            "octop_target_policy": "explicit",
            "octop_explicit_target": {
                "device_id": "other",
                "target_kind": "device",
                "working_dir": "/x",
            },
        }
    )
    # owned() returns grant for whatever id is requested
    rig.device.grant_version = 3
    try:
        result = rig.team.submit_peer(
            from_agent_id="host",
            to_agent_id="member",
            user_id=1,
            message="explicit device",
            source_thread_id="room",
            metadata={"session_key": "host:dashboard:1"},
        )
        msg = rig.team.inbox.get(result.job_id)
        assert msg is not None
        cfg = msg.metadata[_KEY]["configurable"]
        assert cfg["octop_target_policy"] == "explicit"
        assert cfg["octop_device_target"]["device_id"] == "other"
        assert cfg["octop_device_target"]["working_dir"] == "/x"
        # Shared parent configurable must remain untouched (no in-place mutation).
        assert shared.get("octop_target_policy") is None
        assert shared["octop_device_target"]["device_id"] == "pc"
        await rig.tracker.cancel_task_run(1, "run-c")
    finally:
        tv._PENDING_ASK_TARGET.reset(pending)
        var_child_runnable_config.reset(token)
        await close(rig)
