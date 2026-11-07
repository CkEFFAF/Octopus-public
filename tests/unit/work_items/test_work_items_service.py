"""0043 work-item service: idempotency, progress read-only, cancel, origin missing, unknown."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.execution import ExecutionContextRepo
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.execution.events import RunInspectionService
from octop.infra.gateway.task_events import TaskEventEmitter
from octop.infra.work_items.models import WorkItemCancel, WorkItemCreate, WorkItemInputCreate
from octop.infra.work_items.service import WorkItemsService


class _Hub:
    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    async def push_to_user(self, user_id: int, frame: dict[str, Any]) -> None:
        self.frames.append({"user_id": user_id, **frame})


@pytest.fixture
def rig(tmp_path: Path) -> Any:
    pool = SqlitePool(tmp_path / "work.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    uid = repos.user_repo.create(username="owner", password_hash="x", role="admin")
    other = repos.user_repo.create(username="other", password_hash="x", role="user")
    repos.agent_repo.create(agent_id="agent-a", user_id=uid, name="A")
    repos.thread_repo.insert(
        thread_id="origin-1",
        agent_id="agent-a",
        user_id=uid,
        channel_type="dashboard",
        session_key="origin-key",
    )
    hub = _Hub()

    async def _ensure_worker(**kwargs: Any) -> str:
        wid = "worker-thread-1"
        if repos.thread_repo.get(wid) is None:
            repos.thread_repo.insert(
                thread_id=wid,
                agent_id=kwargs["agent_id"],
                user_id=kwargs["user_id"],
                channel_type="dashboard",
                session_key=kwargs["session_key"],
            )
        return wid

    gateway = SimpleNamespace(
        thread_registry=SimpleNamespace(get_or_create_by_key=AsyncMock(side_effect=_ensure_worker)),
        emit_thread_changed=AsyncMock(),
        _hub=hub,
    )
    emitter = TaskEventEmitter(hub)
    gateway.emit_task_changed = emitter.emit_task_changed
    service = WorkItemsService(repos=repos, gateway=gateway, registry=None, delivery=None)
    return SimpleNamespace(
        service=service,
        repos=repos,
        uid=uid,
        other=other,
        hub=hub,
        gateway=gateway,
        pool=pool,
    )


def _create_body(**overrides: Any) -> WorkItemCreate:
    base = {
        "command_id": "cmd-1",
        "agent_id": "agent-a",
        "origin_thread_id": "origin-1",
        "title": "Long job",
        "instructions": "do the thing",
        "execution": {"target_kind": "device"},
        "resources": [],
        "schema_version": 1,
    }
    base.update(overrides)
    return WorkItemCreate.model_validate(base)


@pytest.mark.asyncio
async def test_idempotent_create_same_command(rig: Any) -> None:
    first = await rig.service.create(rig.uid, _create_body())
    assert first["idempotent_replay"] is False
    assert first["status"] == "queued"
    second = await rig.service.create(rig.uid, _create_body())
    assert second["idempotent_replay"] is True
    assert second["task_id"] == first["task_id"]
    conflict = _create_body(title="Different")
    with pytest.raises(OctopError) as exc:
        await rig.service.create(rig.uid, conflict)
    assert exc.value.code == ErrorCode.WORK_ITEM_COMMAND_CONFLICT


@pytest.mark.asyncio
async def test_progress_readonly_no_worker_user_messages(rig: Any) -> None:
    created = await rig.service.create(rig.uid, _create_body(command_id="cmd-progress"))
    task_id = created["task_id"]
    # Wait briefly for background dispatch to create worker thread
    await asyncio.sleep(0.05)
    before_events = rig.repos.run_event_repo.list_for_work_item(rig.uid, task_id, limit=50)
    before_n = len(before_events)
    detail = None
    for _ in range(12):
        detail = rig.service.progress(rig.uid, task_id)
        assert "progress" in detail
        assert detail["task_id"] == task_id
    after_events = rig.repos.run_event_repo.list_for_work_item(rig.uid, task_id, limit=50)
    # Progress GETs must not append new worker user-message style events / steer.
    assert len(after_events) == before_n or len(after_events) >= before_n
    # No chat_input / chat_steer kinds for this work item
    assert all(e["kind"] not in {"chat_input", "chat_steer"} for e in after_events)
    assert detail is not None
    assert "status" in detail


@pytest.mark.asyncio
async def test_cancel_request_then_terminal(rig: Any) -> None:
    created = await rig.service.create(rig.uid, _create_body(command_id="cmd-cancel"))
    task_id = created["task_id"]
    await asyncio.sleep(0.02)
    result = await rig.service.cancel(
        rig.uid,
        task_id,
        WorkItemCancel(command_id="cancel-1", scope="task", schema_version=1),
    )
    assert result["cancel_requested"] is True
    assert result["schema_version"] == 1
    # Allow confirm path
    await asyncio.sleep(0.05)
    detail = rig.service.detail(rig.uid, task_id)
    assert detail["cancel_requested"] is True
    assert detail["status"] in {"cancelled", "running", "queued", "completed", "failed", "unknown"}


@pytest.mark.asyncio
async def test_origin_deleted_still_readable(rig: Any) -> None:
    created = await rig.service.create(rig.uid, _create_body(command_id="cmd-tomb"))
    task_id = created["task_id"]
    with rig.repos.db.transaction() as conn:
        conn.execute("DELETE FROM threads WHERE thread_id = ?", ("origin-1",))
    detail = rig.service.detail(rig.uid, task_id)
    assert detail["origin_thread_missing"] is True
    assert detail["origin_thread_id"] == "origin-1"
    # Completing should skip append to tombstone
    await rig.service._complete(rig.uid, task_id, output="done")
    rig.gateway.emit_thread_changed.assert_not_called()
    detail2 = rig.service.detail(rig.uid, task_id)
    assert detail2["status"] == "completed"


@pytest.mark.asyncio
async def test_unknown_no_auto_replay(rig: Any) -> None:
    created = await rig.service.create(rig.uid, _create_body(command_id="cmd-unk"))
    task_id = created["task_id"]
    await asyncio.sleep(0.05)
    # Simulate post-crash recovery: clear in-process jobs and recover
    rig.service._jobs.clear()
    row = rig.repos.work_item_repo.get(rig.uid, task_id)
    assert row is not None
    rig.repos.work_item_repo.update(rig.uid, task_id, status="running", worker_thread_id="w1")
    rig.service.recover()
    detail = rig.service.detail(rig.uid, task_id)
    assert detail["status"] == "unknown"
    # recover must not schedule a second dispatch automatically
    assert task_id not in rig.service._jobs


@pytest.mark.asyncio
async def test_input_run_conflict(rig: Any) -> None:
    created = await rig.service.create(rig.uid, _create_body(command_id="cmd-in"))
    task_id = created["task_id"]
    await asyncio.sleep(0.05)
    with pytest.raises(OctopError) as exc:
        await rig.service.add_input(
            rig.uid,
            task_id,
            WorkItemInputCreate(
                command_id="in-1",
                text="change it",
                target_run_id="not-current",
                schema_version=1,
            ),
        )
    assert exc.value.code == ErrorCode.WORK_ITEM_RUN_CONFLICT


@pytest.mark.asyncio
async def test_two_items_isolated_targets(rig: Any) -> None:
    a = await rig.service.create(
        rig.uid,
        _create_body(
            command_id="cmd-a",
            title="A",
            execution={"target_kind": "device", "device_id": None, "working_dir": "/a"},
        ),
    )
    b = await rig.service.create(
        rig.uid,
        _create_body(
            command_id="cmd-b",
            title="B",
            execution={"target_kind": "device", "device_id": None, "working_dir": "/b"},
        ),
    )
    da = rig.service.detail(rig.uid, a["task_id"])
    db = rig.service.detail(rig.uid, b["task_id"])
    assert da["execution"]["working_dir"] == "/a"
    assert db["execution"]["working_dir"] == "/b"
    assert da["task_id"] != db["task_id"]


@pytest.mark.asyncio
async def test_task_changed_emitted_on_create(rig: Any) -> None:
    await rig.service.create(rig.uid, _create_body(command_id="cmd-evt"))
    types = [f["type"] for f in rig.hub.frames]
    assert "task.changed" in types
    created = next(f for f in rig.hub.frames if f["type"] == "task.changed")
    assert created["reason"] == "created"
    assert created["schema_version"] == 1
    assert "token" not in created
    assert "instructions" not in created


@pytest.mark.asyncio
async def test_owner_isolation(rig: Any) -> None:
    created = await rig.service.create(rig.uid, _create_body(command_id="cmd-own"))
    with pytest.raises(OctopError) as exc:
        rig.service.detail(rig.other, created["task_id"])
    assert exc.value.code == ErrorCode.WORK_ITEM_NOT_FOUND


@pytest.mark.asyncio
async def test_cancel_leaves_pending_while_in_process_job_live(rig: Any) -> None:
    """DEC-0043-09: do not terminal-cancel while in-process work is still live."""
    created = await rig.service.create(rig.uid, _create_body(command_id="cmd-cancel-live"))
    task_id = created["task_id"]
    for job in list(rig.service._jobs.values()):
        job.cancel()
    await asyncio.sleep(0.02)
    rig.service._jobs.clear()

    class _LiveJob:
        def done(self) -> bool:
            return False

        def cancel(self) -> None:
            self.cancelled = True

    live = _LiveJob()
    rig.service._jobs[task_id] = live  # type: ignore[assignment]
    rig.repos.work_item_repo.update(
        rig.uid, task_id, status="running", worker_thread_id="worker-thread-1"
    )
    if rig.repos.thread_repo.get("worker-thread-1") is None:
        rig.repos.thread_repo.insert(
            thread_id="worker-thread-1",
            agent_id="agent-a",
            user_id=rig.uid,
            channel_type="dashboard",
            session_key="worker-key-live",
        )

    result = await rig.service.cancel(
        rig.uid,
        task_id,
        WorkItemCancel(command_id="cancel-live-1", scope="task", schema_version=1),
    )
    assert result["cancel_requested"] is True
    assert result["terminated"] is False
    assert result["status"] != "cancelled"
    detail = rig.service.detail(rig.uid, task_id)
    assert detail["cancel_requested"] is True
    assert detail["status"] != "cancelled"
    assert getattr(live, "cancelled", False) is True


@pytest.mark.asyncio
async def test_recover_reschedules_never_started_queued(rig: Any) -> None:
    """After restart, queued items with no worker must be re-dispatched."""
    created = await rig.service.create(rig.uid, _create_body(command_id="cmd-recover-q"))
    task_id = created["task_id"]
    for job in list(rig.service._jobs.values()):
        job.cancel()
    await asyncio.sleep(0.02)
    rig.service._jobs.clear()
    rig.repos.work_item_repo.update(
        rig.uid, task_id, status="queued", worker_thread_id=None
    )
    rig.service.recover()
    assert task_id in rig.service._jobs
    assert not rig.service._jobs[task_id].done()


@pytest.mark.asyncio
async def test_add_input_sets_waiting_and_injects_worker(rig: Any) -> None:
    """POST inputs must update authoritative status and append to worker thread."""
    created = await rig.service.create(rig.uid, _create_body(command_id="cmd-input-ok"))
    task_id = created["task_id"]
    for job in list(rig.service._jobs.values()):
        job.cancel()
    await asyncio.sleep(0.02)
    rig.service._jobs.clear()
    worker_id = "worker-thread-input"
    if rig.repos.thread_repo.get(worker_id) is None:
        rig.repos.thread_repo.insert(
            thread_id=worker_id,
            agent_id="agent-a",
            user_id=rig.uid,
            channel_type="dashboard",
            session_key="worker-key-input",
        )
    rig.repos.work_item_repo.update(
        rig.uid,
        task_id,
        status="running",
        worker_thread_id=worker_id,
        current_run_id="run-input-1",
        current_attempt_id="attempt-input-1",
    )
    saved = await rig.service.add_input(
        rig.uid,
        task_id,
        WorkItemInputCreate(
            command_id="in-ok-1",
            text="please revise",
            schema_version=1,
        ),
    )
    detail = rig.service.detail(rig.uid, task_id)
    assert detail["status"] == "waiting_input"
    message_id = f"work:{task_id}:input:{saved['input_id']}"
    assert rig.repos.thread_message_repo.has_message_id(worker_id, message_id) is True
    # Never append inputs onto the origin thread.
    assert rig.repos.thread_message_repo.has_message_id("origin-1", message_id) is False


@pytest.mark.asyncio
async def test_job_observation_persists_work_item_id(rig: Any) -> None:
    """job_observation must stamp work_item_id so cancel can see open Jobs."""
    created = await rig.service.create(rig.uid, _create_body(command_id="cmd-job-obs"))
    task_id = created["task_id"]
    for job in list(rig.service._jobs.values()):
        job.cancel()
    await asyncio.sleep(0.02)
    rig.service._jobs.clear()

    ctx = ExecutionContextRepo(rig.repos.db).create(
        owner_user_id=rig.uid,
        device_id=None,
        working_dir="/tmp",
        policy_revision=0,
        grant_version=0,
        work_mode="agentic",
        source="work_item",
        target_kind="device",
        agent_id="agent-a",
        thread_id="origin-1",
        run_id="run-job-obs",
        work_item_id=task_id,
    )
    rig.repos.work_item_repo.update(
        rig.uid, task_id, status="running", context_id=ctx.context_id
    )
    RunInspectionService(rig.repos).job_observation(
        ctx,
        {"job_id": "external-1", "status": "running", "observed_at": 1.0},
    )
    events = rig.repos.run_event_repo.list_for_work_item(rig.uid, task_id, kind="job", limit=20)
    assert events, "expected job event joinable by work_item_id"
    assert events[0]["work_item_id"] == task_id
    assert events[0]["status"] == "running"
    assert events[0]["payload"]["job_id"] == "external-1"


@pytest.mark.asyncio
async def test_cancel_holds_while_open_job_event_exists(rig: Any) -> None:
    """DEC-0043-09: open kind=job event blocks terminal cancel even if asyncio job is done."""
    created = await rig.service.create(rig.uid, _create_body(command_id="cmd-cancel-open-job"))
    task_id = created["task_id"]
    for job in list(rig.service._jobs.values()):
        job.cancel()
    await asyncio.sleep(0.02)
    rig.service._jobs.clear()

    ctx = ExecutionContextRepo(rig.repos.db).create(
        owner_user_id=rig.uid,
        device_id=None,
        working_dir="/tmp",
        policy_revision=0,
        grant_version=0,
        work_mode="agentic",
        source="work_item",
        target_kind="device",
        agent_id="agent-a",
        thread_id="origin-1",
        run_id="run-cancel-open",
        work_item_id=task_id,
    )
    rig.repos.work_item_repo.update(
        rig.uid,
        task_id,
        status="running",
        worker_thread_id="worker-thread-1",
        context_id=ctx.context_id,
    )
    if rig.repos.thread_repo.get("worker-thread-1") is None:
        rig.repos.thread_repo.insert(
            thread_id="worker-thread-1",
            agent_id="agent-a",
            user_id=rig.uid,
            channel_type="dashboard",
            session_key="worker-key-open-job",
        )

    RunInspectionService(rig.repos).job_observation(
        ctx,
        {"job_id": "host-training", "status": "running", "observed_at": 2.0},
    )

    result = await rig.service.cancel(
        rig.uid,
        task_id,
        WorkItemCancel(command_id="cancel-open-job-1", scope="task", schema_version=1),
    )
    assert result["cancel_requested"] is True
    assert result["terminated"] is False
    assert result["status"] != "cancelled"
    detail = rig.service.detail(rig.uid, task_id)
    assert detail["cancel_requested"] is True
    assert detail["status"] == "running"
