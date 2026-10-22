"""Schedule center ordering, bounded pages and user isolation on real SQLite."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from tests.unit.agents.test_collaboration_resources import rig as listing_rig

from octop.api.routers.cron import schedule_page
from octop.infra.cron.listing import schedule_frequency
from octop.infra.cron.manager import CronManager
from octop.infra.errors import OctopError

rig = listing_rig


def seed(rig: Any) -> CronManager:
    rig.repos.session_repo.upsert(
        session_key="root",
        agent_id="parent",
        user_id=rig.owner,
        channel_type="dashboard",
        chat_type="dm",
        thread_id="root",
    )
    rig.repos.thread_repo.update_title("root", "Training Run")
    for name, agent, user, trigger, kind, meta in (
        ("once", "parent", rig.owner, "date:2099-01-01T09:00:00", "user", {}),
        ("minute", "child", rig.owner, "cron:* * * * *", "user", {}),
        ("hour", "parent", rig.owner, "interval:3600", "user", {}),
        ("daily", "parent", rig.owner, "cron:0 9 * * *", "user", {}),
        ("weekly", "child", rig.owner, "cron:0 9 * * mon", "user", {}),
        ("ended", "parent", rig.owner, "interval:1", "self_reminder", {"fires": 1, "max_fires": 1}),
        ("other-user", "other", rig.outsider, "interval:1", "user", {}),
        ("foreign-on-owned", "parent", rig.outsider, "interval:1", "user", {}),
    ):
        rig.repos.cron_repo.create(
            cron_id=name,
            name=name,
            agent_id=agent,
            user_id=user,
            trigger=trigger,
            prompt="Check progress",
            session_key="root",
            kind=kind,
            meta=meta,
        )
    return CronManager(
        gateway=SimpleNamespace(),
        delivery_service=SimpleNamespace(),
        repos=rig.repos,
        timezone="Asia/Shanghai",
    )


def test_ordered_five_item_pages_and_filters(rig: Any) -> None:
    manager = seed(rig)
    first = manager.list_page(user_id=rig.owner)
    assert [row["id"] for row in first["items"]] == ["once", "minute", "hour", "daily", "weekly"]
    assert first["total"] == 6 and first["next_offset"] == 5
    assert first["counts"] == {"schedules": 5, "reminders": 1}
    second = manager.list_page(user_id=rig.owner, offset=5)
    assert [row["id"] for row in second["items"]] == ["ended"]
    assert not second["has_more"] and second["next_offset"] is None
    assert second["items"][0]["category"] == "ended"
    assert not second["items"][0]["capabilities"]["manage"]
    assert {row["agent_id"] for row in first["items"]} == {"parent", "child"}
    assert manager.list_page(user_id=rig.owner, agent_id="child")["total"] == 2
    assert manager.list_page(user_id=rig.owner, reminder=True)["total"] == 1
    assert manager.list_page(user_id=rig.owner, category="ended")["total"] == 1
    assert manager.list_page(user_id=rig.owner, search="weekly")["total"] == 1
    assert manager.list_page(user_id=rig.owner, search="training run")["total"] == 4
    assert first["items"][0]["thread_title"] == "Training Run"
    assert manager.list_page(user_id=rig.outsider)["total"] == 1
    assert manager.list_page(user_id=rig.owner, thread_id="foreign")["total"] == 0


def test_frequency_uses_actual_cron_and_interval_triggers() -> None:
    now = datetime(2026, 10, 22, tzinfo=UTC)
    assert schedule_frequency("cron:*/5 * * * *", "Asia/Shanghai", now) == 300
    assert schedule_frequency("interval:60", "Asia/Shanghai", now) == 60
    assert schedule_frequency("agently:mail", "Asia/Shanghai", now) == float("inf")


def test_next_fire_summary_includes_tasks_outside_the_visible_page(
    rig: Any, monkeypatch: Any
) -> None:
    manager = seed(rig)
    original = manager.public_view
    monkeypatch.setattr(
        manager,
        "public_view",
        lambda row: {
            **original(row),
            "next_run_at": 100 if row.cron_id == "weekly" else None,
        },
    )
    page = manager.list_page(user_id=rig.owner, limit=1)
    assert page["items"][0]["id"] == "once"
    assert page["next_schedule"] == {"next_run_at": 100, "timezone": "Asia/Shanghai"}


@pytest.mark.asyncio
async def test_page_endpoint_cannot_inspect_shared_expert_even_as_admin(rig: Any) -> None:
    manager = seed(rig)
    rig.repos.agent_repo.set_shared("other", True)
    server = SimpleNamespace(
        app_runtime=SimpleNamespace(
            cron_manager=manager,
            agent_registry=SimpleNamespace(get_row=rig.repos.agent_repo.get),
        )
    )
    owner = SimpleNamespace(id=rig.owner, is_admin=True)
    result = await schedule_page(user=owner, server=server, offset=0, limit=5)
    assert result.total == 6 and len(result.items) == 5
    with pytest.raises(OctopError):
        await schedule_page(agent_id="other", user=owner, server=server, offset=0, limit=5)
