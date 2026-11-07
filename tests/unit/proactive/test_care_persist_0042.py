"""0042: proactive care fixed target + persist-before-push."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from octop.infra.cron.origin_target import care_session_key
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.agents import AgentRepo
from octop.infra.db.repos.sessions import SessionRepo
from octop.infra.db.repos.thread_messages import ThreadMessageRepo
from octop.infra.db.repos.threads import ThreadRepo
from octop.infra.db.repos.users import UserRepo
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.history.projection import message_inputs
from octop.infra.proactive.service import ProactiveCareService
from octop.infra.utils.ulid import new_ulid


def test_care_session_key_stable() -> None:
    a = care_session_key(agent_id="ag1", owner_user_id=7)
    b = care_session_key(agent_id="ag1", owner_user_id=7)
    assert a == b
    assert a.endswith(":care")
    assert "ag1" in a


@pytest.mark.asyncio
async def test_care_persists_before_push_and_rereads(tmp_path: Path) -> None:
    db = SqlitePool(tmp_path / "octop.db")
    run_migrations(db)
    user_id = UserRepo(db).create(username="u", password_hash="h", role="user")
    agent_id = new_ulid()
    AgentRepo(db).create(agent_id=agent_id, user_id=user_id, name="bot")
    key = care_session_key(agent_id=agent_id, owner_user_id=user_id)
    thr = "thr_care_1"
    ThreadRepo(db).insert(
        thread_id=thr,
        agent_id=agent_id,
        user_id=user_id,
        channel_type=ThreadRegistry.CHANNEL_DASHBOARD,
        session_key=key,
    )
    SessionRepo(db).upsert(
        session_key=key,
        agent_id=agent_id,
        user_id=user_id,
        channel_type=ThreadRegistry.CHANNEL_DASHBOARD,
        chat_type="care",
        thread_id=thr,
        channel_subject_id=str(user_id),
        channel_chat_type="care",
    )
    msgs = ThreadMessageRepo(db)
    msgs.mark_projection(thr, "ready")

    appended: list[str] = []

    async def aappend(thread_id: str, messages):
        appended.append(thread_id)
        # also project like production path
        msgs.append_if_ready(thread_id, message_inputs(messages, dedupe_missing_ids=True))
        return list(messages)

    harness = MagicMock()
    harness.aappend_messages = aappend
    # Minimal memory/picker path short-circuit: patch run internals by feeding after LLM
    gateway = MagicMock()
    gateway.require_session = MagicMock(
        return_value=SessionRepo(db).get(key)
    )
    gateway._repos = MagicMock(thread_message_repo=msgs)
    gateway.push_session_text = AsyncMock()
    gateway.notify_dashboard_push = AsyncMock()
    gateway.emit_thread_changed = AsyncMock()
    async def _await_op(session, op):
        await op()

    gateway.run_locked_on_session = AsyncMock(side_effect=_await_op)

    agent_manager = MagicMock()
    agent_manager.get_agent.return_value = harness

    care_repo = MagicMock()
    care_repo.list_pushed_episode_ids.return_value = set()
    service = ProactiveCareService(
        gateway=gateway, care_push_repo=care_repo, agent_manager=agent_manager
    )

    # Force the heavy preamble to a known care_text by patching picker + memory + llm
    ep = MagicMock()
    ep.id = "e1"
    ep.occurred_at = None
    ep.people = []
    ep.summary = "s"
    ep.verbatim_quote = "q"
    ep.emotion = "ok"
    ep.intensity = 1

    memory = MagicMock()
    memory.list_episodes.return_value = [ep]
    harness.memory = memory
    harness.workspace.aread_text = AsyncMock(return_value="")
    harness.config.pick_default_model_ref.return_value = "m"
    harness.config.locale = "zh"
    harness.model_factory.get.return_value = MagicMock()

    pick = MagicMock()
    pick.episodes = [ep]
    pick.window_days = 7
    service._picker.pick = MagicMock(return_value=pick)

    with patch("octop.infra.proactive.service.ainvoke_text", AsyncMock(return_value="关心一下")):
        await service.run(agent_id, key, delivery_id="care1")

    assert appended == [thr]
    assert msgs.has_message_id(thr, "care:care1:assistant") is True
    gateway.notify_dashboard_push.assert_awaited()
    assert gateway.notify_dashboard_push.await_args.kwargs.get("source_kind") == "proactive_care"
    assert gateway.notify_dashboard_push.await_args.kwargs.get("delivery_id") == "care1"
    gateway.emit_thread_changed.assert_awaited()
    care_repo.insert.assert_called()

    # Idempotent retry
    appended.clear()
    with patch("octop.infra.proactive.service.ainvoke_text", AsyncMock(return_value="关心一下")):
        await service.run(agent_id, key, delivery_id="care1")
    assert appended == []
