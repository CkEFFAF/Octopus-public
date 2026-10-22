"""Sidebar activity uses real turn flags and authorized scheduler associations."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from tests.unit.agents.test_collaboration_resources import rig as sidebar_rig

from octop.api.routers.chat.history import get_sidebar_status
from octop.infra.cron.manager import CronManager
from octop.infra.errors import OctopError
from octop.infra.gateway.ws.ws_hub import WebSocketHub

rig = sidebar_rig


@pytest.mark.asyncio
async def test_activity_and_schedules_follow_actual_owned_threads(rig: Any) -> None:
    repos = rig.repos
    hub = WebSocketHub()
    for tid in ("root", "foreign", "child-thread", "deleted"):
        hub.mark_turn_active(tid)
    gateway = SimpleNamespace(
        ws_hub=hub, thread_registry=SimpleNamespace(get_thread=repos.thread_repo.get)
    )
    manager = CronManager(
        gateway=gateway, delivery_service=SimpleNamespace(), repos=repos, timezone="Asia/Shanghai"
    )
    repos.session_repo.upsert(
        session_key="root",
        agent_id="parent",
        user_id=rig.owner,
        channel_type="dashboard",
        chat_type="dm",
        thread_id="root",
    )
    for name, enabled, key, user, kind, meta in (
        ("daily", True, "root", rig.owner, "user", {}),
        ("paused", False, "root", rig.owner, "user", {}),
        ("reminder", True, "root", rig.owner, "self_reminder", {"fires": 1, "max_fires": 1}),
        ("missing", False, "missing", rig.owner, "user", {}),
        ("foreign-task", False, "root", rig.outsider, "user", {}),
    ):
        repos.cron_repo.create(
            cron_id=name,
            name=name,
            agent_id="parent",
            user_id=user,
            trigger="cron:0 9 * * *",
            prompt="private task content",
            session_key=key,
            enabled=enabled,
            fresh_thread=True,
            kind=kind,
            meta=meta,
        )
    server = SimpleNamespace(
        app_runtime=SimpleNamespace(
            gateway=gateway,
            cron_manager=manager,
            agent_registry=SimpleNamespace(get_row=repos.agent_repo.get),
        )
    )
    owner = SimpleNamespace(id=rig.owner, is_admin=True)
    await manager.boot()
    try:
        result = await get_sidebar_status("parent", user=owner, server=server)
        assert [row.thread_id for row in result.working_threads] == ["root"]
        schedules = {row.id: row for row in result.schedules}
        assert set(schedules) == {"daily", "paused", "reminder"}
        assert schedules["daily"].next_run_at is not None
        assert schedules["daily"].timezone == "Asia/Shanghai"
        assert schedules["paused"].scheduler_state == "paused"
        assert schedules["reminder"].scheduler_state == "exhausted"
        assert "private task content" not in result.model_dump_json()
        # Session selection/rebinding never creates activity. Schedules follow the
        # canonical current session, including fresh-thread jobs, without mutation.
        repos.thread_repo.insert(
            thread_id="next",
            agent_id="parent",
            user_id=rig.owner,
            channel_type="dashboard",
            session_key="root",
        )
        repos.session_repo.upsert(
            session_key="root",
            agent_id="parent",
            user_id=rig.owner,
            channel_type="dashboard",
            chat_type="dm",
            thread_id="next",
        )
        result = await get_sidebar_status("parent", user=owner, server=server)
        assert [row.thread_id for row in result.working_threads] == ["root"]
        assert {row.thread_id for row in result.schedules} == {"next"}
        hub.mark_turn_idle("root")
        assert not (await get_sidebar_status("parent", user=owner, server=server)).working_threads
        assert len(manager.list_by_agent("parent", include_self_reminders=True)) == 5
        outsider = SimpleNamespace(id=rig.outsider, is_admin=False)
        with pytest.raises(OctopError):
            await get_sidebar_status("parent", user=outsider, server=server)
        repos.agent_repo.set_shared("parent", True)
        result = await get_sidebar_status("parent", user=outsider, server=server)
        assert not result.working_threads and not result.schedules
    finally:
        await manager.shutdown()
