"""Real scheduler and SQLite prove schedule observation and attempt lifecycle."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from tests.unit.agents.test_collaboration_resources import rig as schedule_rig

from octop.infra.cron.delivery import CronDeliveryCommand, CronDeliveryService
from octop.infra.cron.manager import CronCreateSpec, CronManager

rig = schedule_rig


def session(rig: Any) -> Any:
    rig.repos.session_repo.upsert(
        session_key="root",
        agent_id="parent",
        user_id=rig.owner,
        channel_type="dashboard",
        chat_type="dm",
        thread_id="root",
    )
    return rig.repos.session_repo.get("root")


@pytest.mark.asyncio
async def test_real_scheduler_fires_once_and_persists_attempt(rig: Any) -> None:
    original = session(rig)
    delivered = asyncio.Event()

    async def locked(agent: str, key: str, operation: Any) -> None:
        await operation()

    gateway = SimpleNamespace(
        run_in_session=locked,
        require_session=lambda a, k: original,
        thread_registry=SimpleNamespace(get_session=lambda key: original),
    )
    delivery = CronDeliveryService(gateway=gateway, agent_manager=rig.manager, repos=rig.repos)

    async def text(command: Any, actual: Any) -> None:
        delivered.set()

    delivery._deliver_text = text
    manager = CronManager(
        gateway=gateway, delivery_service=delivery, repos=rig.repos, timezone="Asia/Shanghai"
    )
    await manager.boot()
    try:
        row = await manager.create(
            CronCreateSpec(
                cron_id="one-reminder",
                agent_id="parent",
                user_id=rig.owner,
                session_key="root",
                prompt="check progress",
                trigger="date:" + (datetime.now(UTC) + timedelta(seconds=0.3)).isoformat(),
                task_type="text",
                kind="self_reminder",
                meta={"self_reminder": True, "fires": 0, "max_fires": 1},
            )
        )
        projected = manager.public_view(row)
        assert projected["thread_id"] == "root"
        assert projected["timezone"] == "Asia/Shanghai"
        assert projected["next_run_at"] is not None
        assert projected["scheduler_state"] == "scheduled"
        await asyncio.wait_for(delivered.wait(), 3)
        await asyncio.sleep(0.05)
        final = manager.public_view(manager.get(row.cron_id))
        assert final["scheduler_state"] == "exhausted"
        assert final["remaining"] == 0
        assert final["next_run_at"] is None
        attempts = rig.repos.cron_attempt_repo.listing(rig.owner, "parent", row.cron_id)
        assert len(attempts["items"]) == 1
        attempt = attempts["items"][0]
        assert attempt["status"] == "delivered"
        assert attempt["source_thread_id"] == attempt["actual_thread_id"] == "root"
        assert attempt["run_id"] is None
        for _ in range(3):
            manager.public_view(manager.get(row.cron_id))
        assert (
            len(rig.repos.cron_attempt_repo.listing(rig.owner, "parent", row.cron_id)["items"]) == 1
        )
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_session_permission_checked_before_fresh_reset_and_recovery(rig: Any) -> None:
    session(rig)
    reset = AsyncMock()
    foreign = SimpleNamespace(agent_id="parent", user_id=rig.outsider, thread_id="foreign")

    async def locked(a: str, k: str, operation: Any) -> None:
        await operation()

    gateway = SimpleNamespace(
        run_in_session=locked,
        require_session=lambda a, k: foreign,
        thread_registry=SimpleNamespace(reset_by_session_key=reset),
    )
    delivery = CronDeliveryService(gateway=gateway, agent_manager=rig.manager, repos=rig.repos)
    with pytest.raises(ValueError, match="mismatch"):
        await delivery.deliver(
            CronDeliveryCommand(
                cron_id="task",
                cron_name="Task",
                agent_id="parent",
                user_id=rig.owner,
                session_key="root",
                prompt="hello",
                fresh_thread=True,
                task_type="agent",
                model=None,
                mcp_servers=(),
            )
        )
    reset.assert_not_awaited()
    repo = rig.repos.cron_attempt_repo
    assert repo.listing(rig.owner, "parent", "task")["items"][0]["status"] == "failed"
    assert repo.listing(rig.outsider, "parent", "task")["items"] == []
    repo.create("waiting", rig.owner, "parent", "task", None, "timer")
    repo.recover()
    assert repo.listing(rig.owner, "parent", "task")["items"][0]["status"] == "unknown"
    page = repo.listing(rig.owner, "parent", "task", limit=1)
    assert page["has_more"]
    assert len(repo.listing(rig.owner, "parent", "task", before=page["next_cursor"])["items"]) == 1


def test_attempt_latest_window_and_terminal_does_not_regress(rig: Any) -> None:
    repo = rig.repos.cron_attempt_repo
    for i in range(55):
        repo.create(f"attempt-{i}", rig.owner, "parent", "many", None, "manual")
        repo.update(rig.owner, f"attempt-{i}", "completed", result="public")
    page = repo.listing(rig.owner, "parent", "many")
    assert page["items"][0]["attempt_id"] == "attempt-54"
    assert len(page["items"]) == 50 and page["has_more"]
    assert len(repo.listing(rig.owner, "parent", "many", before=page["next_cursor"])["items"]) == 5
    repo.update(rig.owner, "attempt-54", "running", run="late")
    latest = repo.listing(rig.owner, "parent", "many")["items"][0]
    assert latest["status"] == "completed" and latest["run_id"] is None
