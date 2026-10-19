"""Durable input admission, race safety, recovery and HITL boundaries."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from octop_gateway.models import ChannelSubject, InboundMessage, TextContent

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.errors import OctopError
from octop.infra.gateway.input_queue import ChatInputQueue


@pytest.fixture
def setup_queue(tmp_path):
    db = SqlitePool(tmp_path / "queue.db")
    run_migrations(db)
    repos = RepoBundle.from_pool(db)
    owner = repos.user_repo.create(username="owner", password_hash="h", role="user")
    other = repos.user_repo.create(username="other", password_hash="h", role="user")
    repos.agent_repo.create(agent_id="agent", user_id=owner, name="Agent")
    repos.thread_repo.insert(
        thread_id="thread",
        agent_id="agent",
        user_id=owner,
        channel_type="dashboard",
        session_key="session",
    )
    lock = asyncio.Lock()

    async def run_in_session(channel, key, operation):
        assert key == "thread:thread"
        async with lock:
            await operation()

    pending = SimpleNamespace(value=None)
    agent = SimpleNamespace(checkpointer=None)
    agents = SimpleNamespace(
        get_agent=lambda _: agent,
        get_row=lambda agent_id: repos.agent_repo.get(agent_id),
        steering_status=lambda *_: None,
        steer_stream=Mock(return_value={"status": "accepted", "phase": "tool_running"}),
    )
    gateway = SimpleNamespace(
        channel_manager=SimpleNamespace(run_in_session=run_in_session),
        dashboard_channel_id="dashboard",
        ws_hub=SimpleNamespace(push_to_thread=AsyncMock()),
        dispatch_dashboard_input=AsyncMock(),
        processor=SimpleNamespace(
            hitl_coordinator=SimpleNamespace(
                store=SimpleNamespace(resolve_for_session=lambda *a, **k: pending.value)
            )
        ),
    )
    queue = ChatInputQueue(repos, agents, gateway)
    yield queue, repos, owner, other, gateway, lock, pending, agent
    db.close()


def enqueue(setup, command="one"):
    queue, _, owner, *_ = setup
    inbound = InboundMessage(
        channel_id="dashboard",
        channel_type="dashboard",
        tenant_id="agent",
        channel_subject=ChannelSubject(subject_id=str(owner)),
        content=[TextContent(text=command)],
        metadata={"thread_id": "thread", "session_key": "session"},
    )
    return queue.enqueue(
        owner, "agent", "thread", command, {"text": command}, inbound, request_key=command
    )


def test_fifo_idempotency_capacity_and_scope(setup_queue):
    queue, repos, owner, other, *_ = setup_queue
    first = enqueue(setup_queue)
    assert enqueue(setup_queue)["event_id"] == first["event_id"]
    assert queue.existing_queue(owner, "agent", "thread", "one", "one") is not None
    with pytest.raises(ValueError, match="command_conflict"):
        queue.existing_queue(owner, "agent", "thread", "one", "different")
    with pytest.raises(OctopError):
        queue.list(other, "agent", "thread")
    for number in range(9):
        enqueue(setup_queue, str(number))
    with pytest.raises(ValueError, match="queue_full"):
        enqueue(setup_queue, "overflow")
    assert [r["payload"]["command_id"] for r in repos.chat_input_repo.ready()] == ["one"]
    assert [
        r["payload"]["command_id"] for r in repos.chat_input_repo.list(owner, "agent", "thread")
    ] == ["one", *map(str, range(9))]
    assert queue.withdraw(owner, "agent", "thread", "one")["status"] == "withdrawn"
    assert queue.withdraw(owner, "agent", "thread", "one")["status"] == "withdrawn"


def test_claim_and_withdraw_have_exactly_one_winner(setup_queue):
    _, repos, owner, *_ = setup_queue
    enqueue(setup_queue)
    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(
            workers.map(
                lambda status: repos.chat_input_repo.transition(owner, "one", "queued", status),
                ["withdrawn", "dispatching"],
            )
        )
    assert sorted(outcomes) == [False, True]


def test_restart_preserves_only_unstarted_work(setup_queue):
    queue, repos, owner, *_ = setup_queue
    enqueue(setup_queue, "not-started")
    enqueue(setup_queue, "started")
    repos.chat_input_repo.transition(owner, "started", "queued", "dispatching")
    queue.steer(owner, "agent", "thread", "insert", "run", "direction")
    repos.chat_input_repo.recover()
    assert repos.chat_input_repo.get(owner, "not-started")["status"] == "queued"
    assert repos.chat_input_repo.get(owner, "started")["status"] == "unknown"
    assert repos.chat_input_repo.get(owner, "insert")["status"] == "unknown"
    assert [r["payload"]["command_id"] for r in repos.chat_input_repo.ready()] == ["not-started"]


def test_team_threads_do_not_advertise_or_accept_direct_steering(setup_queue):
    queue, repos, owner, *_ = setup_queue
    repos.agent_repo.create(agent_id="team", user_id=owner, name="Team", kind="team")
    repos.thread_repo.insert(
        thread_id="team-thread",
        agent_id="team",
        user_id=owner,
        channel_type="dashboard",
        session_key="team-session",
    )

    assert queue.list(owner, "team", "team-thread")["capabilities"] == {
        "queue": False,
        "steer": False,
    }
    inbound = InboundMessage(
        channel_id="dashboard",
        channel_type="dashboard",
        tenant_id="team",
        channel_subject=ChannelSubject(subject_id=str(owner)),
        content=[TextContent(text="queued")],
        metadata={"thread_id": "team-thread"},
    )
    with pytest.raises(ValueError, match="input_queue_unsupported"):
        queue.enqueue(owner, "team", "team-thread", "queue", {}, inbound, request_key="q")
    with pytest.raises(ValueError, match="steering_unsupported"):
        queue.steer(owner, "team", "team-thread", "insert", "run", "direction")
    assert repos.chat_input_repo.get(owner, "insert") is None
    assert repos.chat_input_repo.get(owner, "queue") is None


def test_input_controls_reject_non_dashboard_and_bridge_threads(setup_queue):
    queue, repos, owner, *_ = setup_queue
    repos.thread_repo.insert(
        thread_id="im-thread",
        agent_id="agent",
        user_id=owner,
        channel_type="feishu",
        session_key="im-session",
    )
    repos.agent_repo.create(
        agent_id="bridge:connection:remote",
        user_id=owner,
        name="Bridge shadow",
    )
    repos.thread_repo.insert(
        thread_id="bridge-thread",
        agent_id="bridge:connection:remote",
        user_id=owner,
        channel_type="dashboard",
        session_key="bridge-session",
    )

    with pytest.raises(OctopError):
        queue.list(owner, "agent", "im-thread")
    with pytest.raises(OctopError):
        queue.steer(owner, "agent", "im-thread", "im-insert", "run", "direction")
    with pytest.raises(OctopError):
        queue.list(owner, "bridge:connection:remote", "bridge-thread")
    with pytest.raises(OctopError):
        queue.steer(
            owner,
            "bridge:connection:remote",
            "bridge-thread",
            "bridge-insert",
            "run",
            "direction",
        )
    with pytest.raises(OctopError):
        queue.promote_to_steer(owner, "agent", "im-thread", "missing", "run")
    with pytest.raises(OctopError):
        queue.promote_to_steer(owner, "bridge:connection:remote", "bridge-thread", "missing", "run")


def test_promote_queued_message_inserts_once_and_preserves_its_snapshot(setup_queue):
    queue, repos, owner, *_ = setup_queue
    queued = enqueue(setup_queue, "to-promote")
    original_payload = queued["payload"]

    first = queue.promote_to_steer(owner, "agent", "thread", "to-promote", "run-1")
    retry = queue.promote_to_steer(owner, "agent", "thread", "to-promote", "run-1")

    assert first["kind"] == "chat_steer"
    assert first["status"] == "accepted"
    assert first["run_id"] == "run-1"
    assert first["payload"]["text"] == "to-promote"
    assert first["payload"]["snapshot"] == original_payload["snapshot"]
    assert first["payload"]["inbound"] == original_payload["inbound"]
    assert retry["event_id"] == first["event_id"]
    assert queue.agents.steer_stream.call_count == 1
    assert [item["event_id"] for item in repos.chat_input_repo.ready()] == []


def test_explicit_steering_rejection_restores_the_original_queue_item(setup_queue):
    queue, repos, owner, *_ = setup_queue
    queued = enqueue(setup_queue, "keep-queued")
    queue.agents.steer_stream.return_value = {"status": "stale_run", "phase": "idle"}

    with pytest.raises(ValueError, match="steering_stale_run"):
        queue.promote_to_steer(owner, "agent", "thread", "keep-queued", "old-run")

    restored = repos.chat_input_repo.get(owner, "keep-queued")
    assert restored["kind"] == "chat_input"
    assert restored["status"] == "queued"
    assert restored["run_id"] == "keep-queued"
    assert restored["payload"] == queued["payload"]
    assert [item["event_id"] for item in repos.chat_input_repo.ready()] == [queued["event_id"]]


def test_uncertain_promotion_stays_unknown_and_is_not_replayed(setup_queue):
    queue, repos, owner, *_ = setup_queue
    enqueue(setup_queue, "uncertain")
    queue.agents.steer_stream.side_effect = RuntimeError("transport outcome lost")

    first = queue.promote_to_steer(owner, "agent", "thread", "uncertain", "run-1")
    retry = queue.promote_to_steer(owner, "agent", "thread", "uncertain", "run-1")

    assert first["status"] == "unknown"
    assert retry["status"] == "unknown"
    assert queue.agents.steer_stream.call_count == 1
    assert repos.chat_input_repo.ready() == []


@pytest.mark.parametrize(
    ("text", "attachments"),
    [("/help", []), ("plain text", [{"name": "image.png"}])],
)
def test_promote_rejects_commands_and_attachments_without_dequeueing(
    setup_queue, text, attachments
):
    queue, repos, owner, *_ = setup_queue
    inbound = InboundMessage(
        channel_id="dashboard",
        channel_type="dashboard",
        tenant_id="agent",
        channel_subject=ChannelSubject(subject_id=str(owner)),
        content=[TextContent(text=text)],
        metadata={"thread_id": "thread", "session_key": "session"},
    )
    queued = queue.enqueue(
        owner,
        "agent",
        "thread",
        "not-plain",
        {"text": text, "attachments": attachments},
        inbound,
        request_key="not-plain",
    )

    with pytest.raises(ValueError, match="steering_requires_plain_text"):
        queue.promote_to_steer(owner, "agent", "thread", "not-plain", "run")

    current = repos.chat_input_repo.get(owner, "not-plain")
    assert current["status"] == "queued"
    assert current["payload"] == queued["payload"]
    assert queue.agents.steer_stream.call_count == 0


@pytest.mark.parametrize("claim_status", ["withdrawn", "dispatching"])
def test_promote_competes_atomically_with_withdraw_or_dispatch(setup_queue, claim_status):
    _, repos, owner, *_ = setup_queue
    enqueue(setup_queue, "race")

    def promote():
        try:
            return repos.chat_input_repo.promote_queued_to_steer(
                owner, "agent", "thread", "race", "run", "race"
            )[1]
        except ValueError:
            return False

    def claim():
        return repos.chat_input_repo.transition(owner, "race", "queued", claim_status)

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda fn: fn(), [promote, claim]))

    assert sum(bool(result) for result in results) == 1


@pytest.mark.asyncio
async def test_withdraw_wins_while_dispatch_waits_for_active_turn(setup_queue):
    queue, repos, owner, _, gateway, lock, *_ = setup_queue
    enqueue(setup_queue)
    await lock.acquire()
    task = asyncio.create_task(queue._dispatch(repos.chat_input_repo.ready()[0]))
    await asyncio.sleep(0)
    assert queue.withdraw(owner, "agent", "thread", "one")["status"] == "withdrawn"
    lock.release()
    await task
    gateway.dispatch_dashboard_input.assert_not_awaited()


@pytest.mark.asyncio
async def test_hitl_and_checkpoint_interrupt_defer_then_execute_once(setup_queue):
    queue, repos, owner, _, gateway, _, pending, agent = setup_queue
    enqueue(setup_queue)
    item = repos.chat_input_repo.ready()[0]
    pending.value = object()
    await queue._dispatch(item)
    assert repos.chat_input_repo.get(owner, "one")["status"] == "queued"
    pending.value = None
    agent.checkpointer = object()
    agent.graph = SimpleNamespace(
        aget_state=AsyncMock(return_value=SimpleNamespace(tasks=[SimpleNamespace(interrupts=[1])]))
    )
    await queue._dispatch(item)
    gateway.dispatch_dashboard_input.assert_not_awaited()
    agent.graph.aget_state.return_value = SimpleNamespace(tasks=[])
    await queue._dispatch(item)
    await queue._dispatch(item)
    gateway.dispatch_dashboard_input.assert_awaited_once()
    assert repos.chat_input_repo.get(owner, "one")["status"] == "applied"


def test_scan_pages_thread_heads_without_starving_later_threads(setup_queue):
    _, repos, owner, *_ = setup_queue
    for number in range(105):
        thread = f"thread-{number}"
        repos.thread_repo.insert(
            thread_id=thread,
            agent_id="agent",
            user_id=owner,
            channel_type="dashboard",
            session_key=thread,
        )
        for item in range(2):
            repos.chat_input_repo.create(
                owner,
                "agent",
                thread,
                f"{number}-{item}",
                kind="chat_input",
                run_id=f"{number}-{item}",
                status="queued",
                payload={"request_key": f"{number}-{item}", "command_id": f"{number}-{item}"},
            )
    first = repos.chat_input_repo.ready()
    second = repos.chat_input_repo.ready(after_seq=first[-1]["seq"])
    assert len(first) == 100
    assert len(second) == 5
    assert len({row["thread_id"] for row in first + second}) == 105
    assert all(row["payload"]["command_id"].endswith("-0") for row in first + second)


def test_unfinished_receipts_survive_recent_history_window(setup_queue):
    queue, repos, owner, *_ = setup_queue
    enqueue(setup_queue, "pending-queue")
    queue.steer(owner, "agent", "thread", "pending-insert", "run", "direction")
    for number in range(105):
        repos.chat_input_repo.create(
            owner,
            "agent",
            "thread",
            f"rejected-{number}",
            kind="chat_steer",
            run_id="run",
            status="busy",
            payload={"command_id": f"rejected-{number}"},
        )
    items = repos.chat_input_repo.list(owner, "agent", "thread")
    assert {row["payload"]["command_id"] for row in items} >= {"pending-queue", "pending-insert"}
    repos.chat_input_repo.finish_run(owner, "agent", "thread", "run")
    assert repos.chat_input_repo.get(owner, "pending-insert")["status"] == "unknown"


@pytest.mark.asyncio
async def test_resume_holds_dashboard_lock_until_completion_and_updates_receipts(setup_queue):
    from unittest.mock import MagicMock

    from octop.infra.gateway.gateway import Gateway

    queue, repos, owner, _, fake_gateway, *_ = setup_queue
    gateway = Gateway.__new__(Gateway)
    gateway._channel_manager = fake_gateway.channel_manager
    gateway._ws_hub = SimpleNamespace(
        mark_turn_active=MagicMock(), mark_turn_idle=MagicMock(), push_to_thread=AsyncMock()
    )
    gateway._inputs = queue
    gateway._dashboard_operations = set()
    started, release = asyncio.Event(), asyncio.Event()

    async def source():
        started.set()
        await release.wait()
        yield "frame"

    async def consume():
        return [frame async for frame in gateway.iter_dashboard_operation("thread", source)]

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 5)
    enqueue(setup_queue)
    dispatch = asyncio.create_task(queue._dispatch(repos.chat_input_repo.ready()[0]))
    await asyncio.sleep(0)
    assert repos.chat_input_repo.get(owner, "one")["status"] == "queued"
    assert queue.withdraw(owner, "agent", "thread", "one")["status"] == "withdrawn"
    queue.steer(owner, "agent", "thread", "resume-insert", "run", "direction")
    await gateway.observe_dashboard_resume(
        owner, "agent", "thread", {"type": "steering_applied", "command_id": "resume-insert"}
    )
    assert repos.chat_input_repo.get(owner, "resume-insert")["status"] == "applied"
    release.set()
    assert await task == ["frame"]
    await dispatch
    fake_gateway.dispatch_dashboard_input.assert_not_awaited()
    assert not gateway._dashboard_operations
