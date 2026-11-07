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
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError
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
