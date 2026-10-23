"""Sidebar activity uses real turn flags and authorized scheduler associations."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from tests.unit.agents.test_collaboration_resources import rig as sidebar_rig

from octop.api.routers.chat.history import get_sidebar_status
from octop.infra.cron.manager import CronManager
from octop.infra.errors import OctopError
from octop.infra.gateway.ws.ws_hub import WebSocketHub

rig = sidebar_rig


def test_background_history_filters_owner_threads_and_omits_commands(rig: Any):
    repo = rig.repos.run_event_repo
    for index, state in enumerate(("running", "completed", "failed", "cancelled")):
        repo.save(
            event_id=f"history-{index}",
            owner=rig.owner,
            agent_id="parent",
            thread_id="root",
            run_id="",
            context_id=None,
            kind="job",
            status=state,
            payload={"command": "secret command", "job_id": "raw-job-id", "output": "secret log"},
        )
    page = repo.background_page(
        rig.owner, "parent", lifecycle="active", thread=None, offset=0, limit=20
    )
    assert page["total"] == 1 and page["items"][0]["status"] == "running"
    assert page["counts"] == {"active": 1, "completed": 1, "failed": 1, "inactive": 1}
    assert "secret" not in str(page) and "raw-job-id" not in str(page)
    assert (
        repo.background_page(
            rig.owner, "parent", lifecycle="completed", thread=None, offset=0, limit=20
        )["items"][0]["id"]
        == "history-1"
    )
    assert (
        repo.background_page(
            rig.outsider, "parent", lifecycle="all", thread=None, offset=0, limit=20
        )["total"]
        == 0
    )
    assert (
        repo.background_page(
            rig.owner, "parent", lifecycle="all", thread="foreign", offset=0, limit=20
        )["total"]
        == 0
    )


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
        services=SimpleNamespace(repos=repos),
        app_runtime=SimpleNamespace(
            gateway=gateway,
            cron_manager=manager,
            agent_registry=SimpleNamespace(get_row=repos.agent_repo.get),
        ),
    )
    owner = SimpleNamespace(id=rig.owner, is_admin=True)
    await manager.boot()
    try:
        with repos.db.transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO thread_metadata(thread_id) VALUES ('root')")
            conn.execute(
                "UPDATE thread_metadata SET snapshot_json=? WHERE thread_id='root'",
                (
                    json.dumps(
                        {"brief": {"one_liner": "检查实验", "in_progress": [{"text": "正在验证"}]}}
                    ),
                ),
            )
        result = await get_sidebar_status("parent", user=owner, server=server)
        assert [row.thread_id for row in result.working_threads] == ["root"]
        assert result.working_threads[0].metadata["one_liner"] == "检查实验"
        assert result.working_threads[0].metadata["current_progress"] == "正在验证"
        schedules = {row.id: row for row in result.schedules}
        assert set(schedules) == {"daily", "paused", "reminder"}
        assert schedules["daily"].next_run_at is not None
        assert schedules["daily"].timezone == "Asia/Shanghai"
        assert schedules["daily"].created_at > 0
        assert schedules["daily"].last_run_at is None
        assert schedules["reminder"].self_reminder is True
        assert schedules["daily"].self_reminder is False
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
        # Persisted background jobs remain visible after the chat turn ends.
        repos.run_event_repo.save(
            event_id="background-1",
            owner=rig.owner,
            agent_id="parent",
            thread_id="root",
            run_id="",
            context_id=None,
            kind="job",
            status="running",
            payload={"job_id": "job-1", "command": "private command", "output": "private logs"},
        )
        owned = await get_sidebar_status("parent", user=owner, server=server)
        assert [row.thread_id for row in owned.working_threads] == ["root"]
        assert owned.background_tasks[0].name == "job-1"
        assert "private" not in str(owned.background_tasks)
        foreign = await get_sidebar_status("parent", user=outsider, server=server)
        assert not foreign.background_tasks
    finally:
        await manager.shutdown()
