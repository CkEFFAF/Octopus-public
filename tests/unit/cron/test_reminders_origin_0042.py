"""0042: self-reminder origin_thread binding, idempotent delivery, rebind isolation."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.config import var_child_runnable_config

from octop.config import OctopConfig
from octop.infra.cron.delivery import CronDeliveryCommand, CronDeliveryService, command_from_row
from octop.infra.cron.manager import CronCreateSpec, CronManager
from octop.infra.cron.origin_target import OriginThreadError, prepare_self_reminder_command
from octop.infra.cron.self_reminder import (
    ERR_ORIGIN_THREAD_MISSING,
    ERR_ORIGIN_THREAD_UNAVAILABLE,
    NEEDS_RETARGET_KEY,
    ORIGIN_THREAD_ID_KEY,
    backfill_origin_from_session,
    build_wakeup_prompt,
    is_self_reminder_row,
    stamp_origin_meta,
)
from octop.infra.cron.tools import build_self_reminder_tools
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.agents import AgentRepo
from octop.infra.db.repos.cron_attempts import CronAttemptRepo
from octop.infra.db.repos.sessions import SessionRepo
from octop.infra.db.repos.thread_messages import ThreadMessageRepo
from octop.infra.db.repos.threads import ThreadRepo
from octop.infra.db.repos.users import UserRepo
from octop.infra.db.services import build_shared_services
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.utils.paths import PathLayout
from octop.infra.utils.ulid import new_ulid


def _mark_ready(db, thread_id: str) -> None:
    ThreadMessageRepo(db).mark_projection(thread_id, "ready")


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
    gw.thread_registry.get_bound_thread_id = MagicMock(return_value="thr_origin_a")
    gw.thread_registry.get_or_create_by_key = AsyncMock(return_value="thr_origin_a")
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


def _seed_threads(tmp_path: Path) -> tuple[Any, str, str, str, int, str]:
    db = SqlitePool(tmp_path / "octop.db")
    run_migrations(db)
    user_id = UserRepo(db).create(username="u", password_hash="h", role="user")
    agent_id = new_ulid()
    AgentRepo(db).create(agent_id=agent_id, user_id=user_id, name="bot")
    session_key = ThreadRegistry.dashboard_key(agent_id=agent_id, user_id=user_id)
    thr_a = "thr_origin_a"
    thr_b = "thr_origin_b"
    threads = ThreadRepo(db)
    sessions = SessionRepo(db)
    for tid in (thr_a, thr_b):
        threads.insert(
            thread_id=tid,
            agent_id=agent_id,
            user_id=user_id,
            channel_type=ThreadRegistry.CHANNEL_DASHBOARD,
            session_key=session_key,
        )
    sessions.upsert(
        session_key=session_key,
        agent_id=agent_id,
        user_id=user_id,
        channel_type=ThreadRegistry.CHANNEL_DASHBOARD,
        chat_type=ThreadRegistry.CHAT_TYPE_DM,
        thread_id=thr_a,
    )
    for tid in (thr_a, thr_b):
        ThreadMessageRepo(db).mark_projection(tid, "ready")
    return db, agent_id, session_key, thr_a, user_id, thr_b


@pytest.mark.asyncio
async def test_schedule_self_check_stamps_immutable_origin(tmp_path: Path) -> None:
    services = _make_services(tmp_path)
    agent_id = new_ulid()
    user_id = services.repos.user_repo.create(username="u1", password_hash="x", role="user")
    services.repos.agent_repo.create(agent_id=agent_id, user_id=user_id, name="a1")
    mgr = _make_manager(services)
    # Real ensure_session path: bind via registry mock returning thr_origin_a
    schedule = _tool_by_name(build_self_reminder_tools(mgr), "schedule_self_check")
    session_key = ThreadRegistry.dashboard_key(agent_id=agent_id, user_id=user_id)

    with _configurable(
        agent_id=agent_id,
        user=str(user_id),
        session_key=session_key,
        thread_id="thr_origin_a",
    ):
        raw = await schedule.ainvoke({"in_minutes": 30, "purpose": "check progress"})
    data = json.loads(raw)
    assert data.get("origin_thread_id") == "thr_origin_a"
    row = mgr.get(data["reminder_id"])
    assert row is not None
    assert (row.meta or {}).get(ORIGIN_THREAD_ID_KEY) == "thr_origin_a"
    assert (row.meta or {}).get(NEEDS_RETARGET_KEY) is False
    # Immutable: stamp again must not overwrite
    stamped = stamp_origin_meta(row.meta, thread_id="thr_other")
    assert stamped[ORIGIN_THREAD_ID_KEY] == "thr_origin_a"


def test_backfill_or_needs_retarget(tmp_path: Path) -> None:
    db, agent_id, session_key, thr_a, user_id, _thr_b = _seed_threads(tmp_path)
    sessions = SessionRepo(db)
    threads = ThreadRepo(db)

    row = MagicMock()
    row.cron_id = "c1"
    row.agent_id = agent_id
    row.user_id = user_id
    row.session_key = session_key
    row.meta = {"self_reminder": True}

    origin, meta, err = backfill_origin_from_session(
        row, session_repo=sessions, thread_repo=threads
    )
    assert err is None
    assert origin == thr_a
    assert meta[ORIGIN_THREAD_ID_KEY] == thr_a

    missing = MagicMock()
    missing.cron_id = "c2"
    missing.agent_id = agent_id
    missing.user_id = user_id
    missing.session_key = "no-such-session"
    missing.meta = {"self_reminder": True}

    origin2, meta2, err2 = backfill_origin_from_session(
        missing, session_repo=sessions, thread_repo=threads
    )
    assert origin2 is None
    assert err2 == ERR_ORIGIN_THREAD_MISSING
    assert meta2[NEEDS_RETARGET_KEY] is True


@pytest.mark.asyncio
async def test_ac_0042_01_rebind_writes_only_origin_history(tmp_path: Path) -> None:
    """Create on A; rebind dashboard key to B; delivery must append only to A."""
    db, agent_id, session_key, thr_a, user_id, thr_b = _seed_threads(tmp_path)
    sessions = SessionRepo(db)
    threads = ThreadRepo(db)
    messages = ThreadMessageRepo(db)
    # Rebind live dashboard key to B
    sessions.set_thread(session_key, thr_b)
    assert sessions.get(session_key).thread_id == thr_b

    appended_threads: list[str] = []

    async def append(thread_id: str, msgs):
        appended_threads.append(thread_id)
        return list(msgs)

    harness = MagicMock()
    harness.aappend_messages = append
    agent_manager = MagicMock()
    agent_manager.get_agent.return_value = harness

    gateway = MagicMock()
    async def _await_op(session, op):
        await op()

    gateway.run_locked_on_session = AsyncMock(side_effect=_await_op)
    gateway.run_in_session = AsyncMock()
    gateway.push_session_text = AsyncMock()
    gateway.notify_dashboard_push = AsyncMock()
    gateway.emit_thread_changed = AsyncMock()
    gateway.require_session = MagicMock(
        side_effect=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("must not use rebound live session_key")
        )
    )
    gateway.thread_registry = ThreadRegistry(session_repo=sessions, thread_repo=threads)

    from octop.config import OctopConfig
    from octop.infra.db.services import build_shared_services
    from octop.infra.utils.paths import PathLayout

    services = build_shared_services(db=db, paths=PathLayout(tmp_path), config=OctopConfig())
    # Wire attempt repo etc.
    service = CronDeliveryService(
        gateway=gateway, agent_manager=agent_manager, repos=services.repos
    )

    command = CronDeliveryCommand(
        cron_id="j1",
        cron_name="self",
        agent_id=agent_id,
        user_id=user_id,
        session_key=session_key,
        prompt="wake up",
        fresh_thread=False,
        task_type="text",
        model=None,
        mcp_servers=(),
        origin_thread_id=thr_a,
        delivery_id="deliv1",
        source_kind="self_reminder",
    )
    await service.deliver(command)

    assert appended_threads == [thr_a]
    # Real DB projection re-read (AC-0042-04)
    assert messages.has_message_id(thr_a, "cron:deliv1:assistant") is True
    assert messages.has_message_id(thr_b, "cron:deliv1:assistant") is False
    gateway.notify_dashboard_push.assert_awaited()
    kwargs = gateway.notify_dashboard_push.await_args.kwargs
    assert kwargs.get("delivery_id") == "deliv1"
    assert kwargs.get("source_kind") == "self_reminder"
    gateway.emit_thread_changed.assert_awaited()


@pytest.mark.asyncio
async def test_ac_0042_03_idempotent_same_delivery_id(tmp_path: Path) -> None:
    db, agent_id, session_key, thr_a, user_id, _thr_b = _seed_threads(tmp_path)
    sessions = SessionRepo(db)
    threads = ThreadRepo(db)
    from octop.config import OctopConfig
    from octop.infra.db.services import build_shared_services
    from octop.infra.utils.paths import PathLayout

    services = build_shared_services(db=db, paths=PathLayout(tmp_path), config=OctopConfig())
    from octop.infra.history.projection import message_inputs

    # Pre-seed projection as already persisted
    services.repos.thread_message_repo.append_if_ready(
        thr_a,
        message_inputs(
            [AIMessage(content="wake", id="cron:same:assistant")],
            dedupe_missing_ids=True,
        ),
    )

    append_calls: list[str] = []

    async def append(thread_id: str, msgs):
        append_calls.append(thread_id)
        return list(msgs)

    harness = MagicMock()
    harness.aappend_messages = append
    agent_manager = MagicMock()
    agent_manager.get_agent.return_value = harness

    gateway = MagicMock()
    async def _await_op(session, op):
        await op()

    gateway.run_locked_on_session = AsyncMock(side_effect=_await_op)
    gateway.push_session_text = AsyncMock()
    gateway.notify_dashboard_push = AsyncMock()
    gateway.emit_thread_changed = AsyncMock()
    gateway.thread_registry = ThreadRegistry(session_repo=sessions, thread_repo=threads)

    service = CronDeliveryService(
        gateway=gateway, agent_manager=agent_manager, repos=services.repos
    )
    command = CronDeliveryCommand(
        cron_id="j1",
        cron_name="self",
        agent_id=agent_id,
        user_id=user_id,
        session_key=session_key,
        prompt="wake",
        fresh_thread=False,
        task_type="text",
        model=None,
        mcp_servers=(),
        origin_thread_id=thr_a,
        delivery_id="same",
        source_kind="self_reminder",
    )
    await service.deliver(command)
    await service.deliver(command)
    assert append_calls == []  # both skipped — already projected
    assert services.repos.thread_message_repo.has_message_id(thr_a, "cron:same:assistant")


@pytest.mark.asyncio
async def test_ac_0042_05_deleted_origin_fails(tmp_path: Path) -> None:
    db, agent_id, session_key, thr_a, user_id, _thr_b = _seed_threads(tmp_path)
    threads = ThreadRepo(db)
    threads.delete(thr_a)
    from octop.config import OctopConfig
    from octop.infra.db.services import build_shared_services
    from octop.infra.utils.paths import PathLayout

    services = build_shared_services(db=db, paths=PathLayout(tmp_path), config=OctopConfig())
    gateway = MagicMock()
    async def _await_op(session, op):
        await op()

    gateway.run_locked_on_session = AsyncMock(side_effect=_await_op)
    gateway.push_session_text = AsyncMock()
    gateway.notify_dashboard_push = AsyncMock()
    gateway.thread_registry = ThreadRegistry(
        session_repo=services.repos.session_repo, thread_repo=services.repos.thread_repo
    )
    service = CronDeliveryService(
        gateway=gateway, agent_manager=MagicMock(), repos=services.repos
    )
    command = CronDeliveryCommand(
        cron_id="j1",
        cron_name="self",
        agent_id=agent_id,
        user_id=user_id,
        session_key=session_key,
        prompt="wake",
        fresh_thread=False,
        task_type="text",
        model=None,
        mcp_servers=(),
        origin_thread_id=thr_a,
        delivery_id="x",
        source_kind="self_reminder",
    )
    with pytest.raises(OriginThreadError) as ei:
        await service.deliver(command)
    assert ei.value.code == ERR_ORIGIN_THREAD_UNAVAILABLE
    gateway.push_session_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_ac_0042_02_lock_uses_origin_thread_key(tmp_path: Path) -> None:
    db, agent_id, session_key, thr_a, user_id, thr_b = _seed_threads(tmp_path)
    sessions = SessionRepo(db)
    sessions.set_thread(session_key, thr_b)
    from octop.config import OctopConfig
    from octop.infra.db.services import build_shared_services
    from octop.infra.utils.paths import PathLayout

    services = build_shared_services(db=db, paths=PathLayout(tmp_path), config=OctopConfig())
    lock_keys: list[str] = []

    async def capture_lock(session, op):
        lock_keys.append(session.thread_id)
        await op()

    async def append(thread_id: str, msgs):
        return list(msgs)

    harness = MagicMock()
    harness.aappend_messages = append
    agent_manager = MagicMock()
    agent_manager.get_agent.return_value = harness

    gateway = MagicMock()
    gateway.run_locked_on_session = AsyncMock(side_effect=capture_lock)
    gateway.push_session_text = AsyncMock()
    gateway.notify_dashboard_push = AsyncMock()
    gateway.emit_thread_changed = AsyncMock()
    gateway.thread_registry = ThreadRegistry(
        session_repo=services.repos.session_repo, thread_repo=services.repos.thread_repo
    )
    service = CronDeliveryService(
        gateway=gateway, agent_manager=agent_manager, repos=services.repos
    )
    command = CronDeliveryCommand(
        cron_id="j1",
        cron_name="self",
        agent_id=agent_id,
        user_id=user_id,
        session_key=session_key,
        prompt="wake",
        fresh_thread=False,
        task_type="text",
        model=None,
        mcp_servers=(),
        origin_thread_id=thr_a,
        delivery_id="lock1",
        source_kind="self_reminder",
    )
    await service.deliver(command)
    assert lock_keys == [thr_a]


def test_command_from_row_carries_origin() -> None:
    row = MagicMock()
    row.cron_id = "c"
    row.name = "n"
    row.agent_id = "a"
    row.user_id = 1
    row.session_key = "sk"
    row.prompt = "p"
    row.fresh_thread = 1
    row.task_type = "agent"
    row.model = None
    row.mcp_servers = []
    row.kind = "self_reminder"
    row.meta = {
        "self_reminder": True,
        ORIGIN_THREAD_ID_KEY: "thr_x",
        NEEDS_RETARGET_KEY: False,
    }
    cmd = command_from_row(row)
    assert cmd.origin_thread_id == "thr_x"
    assert cmd.fresh_thread is False
    assert cmd.source_kind == "self_reminder"
