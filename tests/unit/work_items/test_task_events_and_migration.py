"""task.changed emitter + migration 036."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.gateway.task_events import TASK_CHANGED_TYPE, TaskEventEmitter


class _Hub:
    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    async def push_to_user(self, user_id: int, frame: dict[str, Any]) -> None:
        self.frames.append(frame)


@pytest.mark.asyncio
async def test_emit_task_changed_frame_shape() -> None:
    hub = _Hub()
    emitter = TaskEventEmitter(hub)
    await emitter.emit_task_changed(
        owner_user_id=1,
        task_id="t1",
        agent_id="a1",
        reason="created",
        status="queued",
        origin_thread_id="o1",
    )
    assert len(hub.frames) == 1
    frame = hub.frames[0]
    assert frame["type"] == TASK_CHANGED_TYPE
    assert frame["schema_version"] == 1
    assert frame["task_id"] == "t1"
    assert frame["reason"] == "created"
    assert "token" not in frame


def test_migration_036_creates_tables(tmp_path: Path) -> None:
    pool = SqlitePool(tmp_path / "m.db")
    run_migrations(pool)
    with pool.connect() as conn:
        version = conn.execute("SELECT version FROM _schema_version").fetchone()[0]
        assert int(version) >= 36
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "work_items" in tables
        assert "work_item_inputs" in tables
        cols = {r[1] for r in conn.execute("PRAGMA table_info(run_events)").fetchall()}
        assert "work_item_id" in cols
        cols2 = {r[1] for r in conn.execute("PRAGMA table_info(execution_contexts)").fetchall()}
        assert "work_item_id" in cols2
    pool.close()
