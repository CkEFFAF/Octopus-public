"""0018 agent self-schedule reminder tools and persistence."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.config import var_child_runnable_config

from octop.config import OctopConfig
from octop.infra.cron.delivery import CronDeliveryService, command_from_row
from octop.infra.cron.job import CronJob
from octop.infra.cron.manager import CronCreateSpec, CronManager
from octop.infra.cron.self_reminder import (
    build_wakeup_prompt,
    is_self_reminder_row,
    resolve_fire_at,
)
from octop.infra.cron.tools import build_cronjob_tools, build_self_reminder_tools
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.utils.paths import PathLayout
from octop.infra.utils.ulid import new_ulid


@contextmanager
def _configurable(**kwargs: object):
    token = var_child_runnable_config.set({"configurable": kwargs})
    try:
        yield
    finally:
        var_child_runnable_config.reset(token)


def _make_services(tmp_path: Path):
    db = SqlitePool(tmp_path / "octop.db")
    run_migrations(db)
    return build_shared_services(db=db, paths=PathLayout(tmp_path), config=OctopConfig())


def _make_manager(services) -> CronManager:
    gw = MagicMock()
    gw.thread_registry = MagicMock()
    gw.thread_registry.get_session = MagicMock(return_value=None)
    gw.thread_registry.get_or_create_by_key = AsyncMock(return_value="thr_test")
    mgr = CronManager(
        gateway=gw,
        delivery_service=CronDeliveryService(
            gateway=gw,
            agent_manager=MagicMock(),
            repos=services.repos,
        ),
        repos=services.repos,
        timezone="UTC",
    )
    mgr._scheduler = MagicMock()
    mgr._scheduler.get_job = MagicMock(return_value=None)
    return mgr


def _tool_by_name(tools: list, name: str):
    for tool in tools:
        if tool.name == name:
            return tool
    raise KeyError(name)


def test_build_wakeup_prompt_contains_marker() -> None:
    text = build_wakeup_prompt(purpose="finish report")
    assert "SELF_CHECK_REMINDER" in text
    assert "finish report" in text


def test_resolve_fire_at_requires_future() -> None:
    now = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        resolve_fire_at(at="2020-01-01T00:00:00Z", now=now)
    fire = resolve_fire_at(in_minutes=30, now=now)
    assert abs((fire - (now + timedelta(minutes=30))).total_seconds()) < 2


@pytest.mark.asyncio
async def test_schedule_self_check_persists_and_hides_from_default_list(tmp_path: Path) -> None:
    services = _make_services(tmp_path)
    agent_id = new_ulid()
    user_id = services.repos.user_repo.create(username="u1", password_hash="x", role="user")
    services.repos.agent_repo.create(agent_id=agent_id, user_id=user_id, name="a1")
    mgr = _make_manager(services)
    tools = build_self_reminder_tools(mgr)
    schedule = _tool_by_name(tools, "schedule_self_check")
    session_key = ThreadRegistry.dashboard_key(agent_id=agent_id, user_id=user_id)

    with _configurable(agent_id=agent_id, user=str(user_id), session_key=session_key):
        raw = await schedule.ainvoke({"in_minutes": 30, "purpose": "check progress"})
    data = json.loads(raw)
    assert "reminder_id" in data
    assert data["purpose"] == "check progress"
    row = mgr.get(data["reminder_id"])
    assert row is not None
    assert is_self_reminder_row(row)
    assert row.trigger.startswith("date:")
    assert row.fresh_thread == 0
    assert row.task_type == "agent"
    assert (row.meta or {}).get("self_reminder") is True

    hidden = mgr.list_by_agent(agent_id, include_self_reminders=False)
    assert all(not is_self_reminder_row(r) for r in hidden)
    shown = mgr.list_by_agent(agent_id, include_self_reminders=True)
    assert any(r.cron_id == data["reminder_id"] for r in shown)

    # Product cron tools list also hides self-reminders.
    cron_tools = build_cronjob_tools(mgr)
    list_tool = _tool_by_name(cron_tools, "cronjob_list")
    with _configurable(agent_id=agent_id, user=str(user_id), session_key=session_key):
        listed = json.loads(await list_tool.ainvoke({}))
    assert all(not item.get("self_reminder") for item in listed)


@pytest.mark.asyncio
async def test_schedule_rejects_past_at(tmp_path: Path) -> None:
    services = _make_services(tmp_path)
    agent_id = new_ulid()
    user_id = services.repos.user_repo.create(username="u2", password_hash="x", role="user")
    services.repos.agent_repo.create(agent_id=agent_id, user_id=user_id, name="a2")
    mgr = _make_manager(services)
    schedule = _tool_by_name(build_self_reminder_tools(mgr), "schedule_self_check")
    with _configurable(agent_id=agent_id, user=str(user_id)):
        raw = await schedule.ainvoke({"at": "2000-01-01T00:00:00Z", "purpose": "x"})
    data = json.loads(raw)
    assert "error" in data


@pytest.mark.asyncio
async def test_cancel_self_check(tmp_path: Path) -> None:
    services = _make_services(tmp_path)
    agent_id = new_ulid()
    user_id = services.repos.user_repo.create(username="u3", password_hash="x", role="user")
    services.repos.agent_repo.create(agent_id=agent_id, user_id=user_id, name="a3")
    mgr = _make_manager(services)
    tools = build_self_reminder_tools(mgr)
    schedule = _tool_by_name(tools, "schedule_self_check")
    cancel = _tool_by_name(tools, "cancel_self_check")
    session_key = ThreadRegistry.dashboard_key(agent_id=agent_id, user_id=user_id)
    with _configurable(agent_id=agent_id, user=str(user_id), session_key=session_key):
        created = json.loads(await schedule.ainvoke({"in_seconds": 120, "purpose": "x"}))
        cancelled = json.loads(await cancel.ainvoke({"reminder_id": created["reminder_id"]}))
    assert cancelled["cancelled"] == created["reminder_id"]
    assert mgr.get(created["reminder_id"]) is None


@pytest.mark.asyncio
async def test_one_shot_disables_after_fire(tmp_path: Path) -> None:
    services = _make_services(tmp_path)
    agent_id = new_ulid()
    user_id = services.repos.user_repo.create(username="u4", password_hash="x", role="user")
    services.repos.agent_repo.create(agent_id=agent_id, user_id=user_id, name="a4")
    mgr = _make_manager(services)
    session_key = ThreadRegistry.dashboard_key(agent_id=agent_id, user_id=user_id)
    fire = datetime.now(UTC) + timedelta(seconds=5)
    spec = CronCreateSpec(
        cron_id=new_ulid(),
        agent_id=agent_id,
        user_id=user_id,
        name="self-check:t",
        trigger=f"date:{fire.isoformat()}",
        prompt=build_wakeup_prompt(purpose="t"),
        session_key=session_key,
        fresh_thread=False,
        task_type="agent",
        kind="self_reminder",
        meta={"self_reminder": True, "max_fires": 1, "fires": 0},
    )
    row = await mgr.create(spec)
    assert command_from_row(row).fresh_thread is False

    delivery = MagicMock()
    delivery.deliver = AsyncMock(return_value="ok")
    job = CronJob.from_row(
        row,
        delivery_service=delivery,
        cron_repo=services.repos.cron_repo,
        audit_repo=services.repos.audit_repo,
    )
    await job.run()
    after = services.repos.cron_repo.get(row.cron_id)
    assert after is not None
    assert after.enabled == 0
    assert (after.meta or {}).get("fires") == 1


def test_tool_description_mentions_wall_clock() -> None:
    tools = build_self_reminder_tools(MagicMock())
    schedule = _tool_by_name(tools, "schedule_self_check")
    assert "wall-clock" in (schedule.description or "").lower()
