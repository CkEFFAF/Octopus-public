"""Task coordination uses persisted facts without dispatching work or crossing accounts."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.config import var_child_runnable_config

from octop.api.deps import current_user, get_server
from octop.api.routers.task_board import router
from octop.infra.cron.manager import CronManager
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.task_archives import TaskArchiveRepo
from octop.infra.db.repos.work_items import WorkItemRepo
from octop.infra.db.services import RepoBundle
from octop.infra.errors import OctopError
from octop.infra.task_board.awareness import ExpertTaskAwarenessMiddleware, build_expert_task_tools
from octop.infra.task_board.models import BoardTask, Schedule
from octop.infra.task_board.overview import TaskOverviewService
from octop.infra.task_board.service import TaskBoardService


@pytest.fixture
def rig(tmp_path: Path) -> Any:
    pool = SqlitePool(tmp_path / "task-overview.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="owner", password_hash="x", role="admin")
    other = repos.user_repo.create(username="other", password_hash="x", role="member")
    repos.agent_repo.create(agent_id="expert", name="Research", user_id=owner)
    repos.agent_repo.create(agent_id="second", name="Writing", user_id=owner)
    for thread, agent, user in (
        ("one", "expert", owner),
        ("two", "expert", owner),
        ("three", "second", owner),
        ("foreign", "expert", other),
    ):
        repos.thread_repo.insert(
            thread_id=thread,
            agent_id=agent,
            user_id=user,
            channel_type="dashboard",
            session_key=f"key-{thread}",
            title=thread,
        )
    manager = SimpleNamespace(_repos=repos, steering_status=lambda *args: None)
    result = SimpleNamespace(
        pool=pool,
        repos=repos,
        owner=owner,
        other=other,
        manager=manager,
        service=TaskOverviewService(manager),
        work=WorkItemRepo(pool),
    )
    yield result
    pool.close()


def work(
    rig: Any,
    identity: str,
    *,
    thread: str = "two",
    owner: int | None = None,
    status: str = "running",
    updated: float | None = None,
) -> None:
    rig.work.insert(
        {
            "task_id": identity,
            "owner_user_id": owner or rig.owner,
            "agent_id": "second" if thread == "three" else "expert",
            "origin_thread_id": thread,
            "command_id": identity,
            "title": f"Task {identity}",
            "status": status,
            "updated_at": updated or time.time(),
        }
    )


def test_filters_and_pagination_are_account_scoped_and_read_only(rig: Any) -> None:
    work(rig, "own-one", thread="one")
    work(rig, "own-two")
    work(rig, "different-expert", thread="three")
    work(rig, "secret", thread="foreign", owner=rig.other)
    page = rig.service.page(rig.owner, agent="expert", limit=1)
    assert page.total == 2 and page.has_more
    second = rig.service.page(rig.owner, agent="expert", offset=1, limit=1)
    assert {r.source_id for r in page.items + second.items} == {"own-one", "own-two"}
    assert rig.service.page(rig.owner, thread="two").items[0].source_id == "own-two"
    assert rig.service.page(rig.owner, query="own-TWO").total == 1
    assert rig.service.page(rig.owner, thread="foreign").total == 0
    assert {
        r["task_id"] for r in rig.work.list(rig.owner, agent_id="expert", status_group="all")
    } == {"own-one", "own-two"}
    assert (
        rig.repos.thread_repo.get("two").last_active == rig.repos.thread_repo.get("two").created_at
    )
    with rig.pool.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM work_item_inputs").fetchone()[0] == 0


def test_native_todos_update_one_plan_and_failed_tool_does_not_write(rig: Any) -> None:
    middleware = ExpertTaskAwarenessMiddleware(rig.manager, "expert")
    cfg = {"configurable": {"user": str(rig.owner), "thread_id": "two", "octop_task_run_id": "run"}}
    token = var_child_runnable_config.set(cfg)
    request = SimpleNamespace(
        tool_call={
            "name": "write_todos",
            "args": {"todos": [{"content": "Verify results", "status": "in_progress"}]},
        }
    )
    try:
        middleware._record(
            request, ToolMessage(content="failed", tool_call_id="call", status="error")
        )
        assert rig.service.page(rig.owner).total == 0
        middleware._record(request, ToolMessage(content="saved", tool_call_id="call"))
        page = rig.service.page(rig.owner)
        assert page.total == 1 and page.items[0].status == "running" and page.items[0].declared
        request.tool_call["args"]["todos"][0]["status"] = "completed"
        middleware._record(request, ToolMessage(content="saved", tool_call_id="call"))
        updated = rig.service.page(rig.owner)
        assert updated.total == 1 and updated.items[0].id == page.items[0].id
        assert updated.items[0].lifecycle == "completed"
    finally:
        var_child_runnable_config.reset(token)


async def test_new_turn_and_tool_see_other_conversations_but_never_other_accounts(rig: Any) -> None:
    work(rig, "other-conversation")
    work(rig, "current", thread="one")
    work(rig, "foreign-secret", thread="foreign", owner=rig.other)
    middleware = ExpertTaskAwarenessMiddleware(rig.manager, "expert")
    token = var_child_runnable_config.set(
        {"configurable": {"user": str(rig.owner), "thread_id": "one", "agent_id": "expert"}}
    )
    try:
        original = HumanMessage(content="What are you working on?", id="question")
        snapshot = await middleware.abefore_model({"messages": [original]}, None)
        text = json.dumps(snapshot, default=str)
        assert "other-conversation" in text
        assert "foreign-secret" not in text
        assert original.content == "What are you working on?"
        tools = build_expert_task_tools(rig.manager, "expert")
        value = json.loads(await tools[0].ainvoke({}))
        assert {r["source_id"] for r in value["items"]} == {"other-conversation", "current"}
        assert await middleware.abefore_model({"messages": snapshot["messages"]}, None) is None
    finally:
        var_child_runnable_config.reset(token)
    with pytest.raises(OctopError):
        rig.service.require_scope(rig.other, "expert", "one")


async def test_isolated_graph_cannot_query_other_conversations(
    rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from octop.infra.workflow_graphs import middleware as graph_middleware

    work(rig, "other-conversation")
    monkeypatch.setattr(graph_middleware, "graph_config", lambda: {"recipe": {"history": "none"}})
    token = var_child_runnable_config.set(
        {"configurable": {"user": str(rig.owner), "thread_id": "one"}}
    )
    try:
        middleware = ExpertTaskAwarenessMiddleware(rig.manager, "expert")
        assert (
            await middleware.abefore_model(
                {"messages": [HumanMessage(content="Check tasks")]}, None
            )
            is None
        )
        tool = build_expert_task_tools(rig.manager, "expert")[0]
        assert json.loads(await tool.ainvoke({})) == {"error": "FORBIDDEN"}
    finally:
        var_child_runnable_config.reset(token)


def test_stale_job_is_unconfirmed_and_archives_preserve_originals(rig: Any) -> None:
    now = time.time()
    work(rig, "old-complete", status="completed", updated=now - 8 * 86400)
    work(rig, "old-failed", status="failed", updated=now - 31 * 86400)
    work(rig, "recent-failed", status="failed", updated=now - 8 * 86400)
    work(rig, "old-running", updated=now - 40 * 86400)
    rig.repos.run_event_repo.save(
        event_id="job",
        owner=rig.owner,
        agent_id="expert",
        thread_id="two",
        run_id="run",
        context_id=None,
        kind="job",
        status="running",
        payload={"title": "Training"},
    )
    with rig.pool.transaction() as conn:
        conn.execute("UPDATE run_events SET updated_at=? WHERE event_id='job'", (now - 100,))
    archives = TaskArchiveRepo(rig.pool)
    archives.archive_terminal(now)
    archives.archive_terminal(now)
    page = rig.service.page(rig.owner)
    assert {r.source_id for r in page.items} == {"recent-failed", "old-running", "job"}
    job = next(r for r in page.items if r.source_id == "job")
    assert job.stale and job.lifecycle == "inactive"
    archived = rig.service.page(rig.owner, state="archived")
    assert {r.source_id for r in archived.items} == {"old-complete", "old-failed"}
    assert rig.work.get(rig.owner, "old-complete") is not None
    rig.work.update(rig.owner, "old-failed", status="running")
    assert "old-failed" in {r.source_id for r in rig.service.page(rig.owner).items}
    assert "old-complete" not in {
        r["task_id"] for r in rig.work.list(rig.owner, status_group="all")
    }


async def test_maintenance_archives_exhausted_schedules_but_keeps_paused_repeats(rig: Any) -> None:
    old = int(time.time() - 8 * 86400)
    for identity, trigger, kind, meta in (
        ("ended-once", "date:2020-01-01T00:00:00", "user", {}),
        ("exhausted", "interval:60", "self_reminder", {"fires": 1, "max_fires": 1}),
        ("paused-repeat", "interval:60", "user", {}),
        ("paused-reminder", "interval:60", "self_reminder", {"fires": 1, "max_fires": 2}),
        ("pending-delivery", "date:2020-01-01T00:00:00", "user", {}),
    ):
        rig.repos.cron_repo.create(
            cron_id=identity,
            agent_id="expert",
            user_id=rig.owner,
            trigger=trigger,
            prompt="Review existing work",
            session_key="key-two",
            enabled=identity != "paused-repeat" and identity != "paused-reminder",
            kind=kind,
            meta=meta,
        )
    with rig.pool.transaction() as conn:
        conn.execute("UPDATE cron_jobs SET last_run_at=?,updated_at=?,last_status='ok'", (old, old))
    rig.repos.cron_attempt_repo.create(
        "pending", rig.owner, "expert", "pending-delivery", "two", "scheduled"
    )
    manager = CronManager(
        gateway=SimpleNamespace(),
        delivery_service=SimpleNamespace(),
        repos=rig.repos,
        timezone="UTC",
    )
    manager._scheduler = SimpleNamespace(running=True, get_job=lambda _: None)
    await manager.archive_task_history()
    assert {
        r.cron_id
        for r in rig.repos.cron_repo.list_by_agent("expert", user_id=rig.owner, archived=True)
    } == {"ended-once", "exhausted"}
    current = {r.cron_id for r in rig.repos.cron_repo.list_by_agent("expert", user_id=rig.owner)}
    assert current == {"paused-repeat", "paused-reminder", "pending-delivery"}
    assert rig.repos.cron_repo.get("paused-repeat").enabled == 0
    assert rig.repos.cron_repo.get("exhausted") is not None


def test_operational_lists_skip_archives_but_explicit_evidence_remains_readable(rig: Any) -> None:
    old = time.time() - 8 * 86400
    rig.service.record_todos(
        rig.owner, "expert", "two", "old-run", [{"content": "Reviewed", "status": "completed"}]
    )
    rig.repos.run_event_repo.save(
        event_id="old-job",
        owner=rig.owner,
        agent_id="expert",
        thread_id="two",
        run_id="old-run",
        context_id=None,
        kind="job",
        status="completed",
        payload={"title": "Done"},
    )
    with rig.pool.transaction() as conn:
        conn.execute("UPDATE run_events SET updated_at=? WHERE event_id='old-job'", (old,))
        conn.execute("UPDATE workbench_records SET updated_at=? WHERE kind='plan'", (old,))
    TaskArchiveRepo(rig.pool).archive_terminal()
    assert not rig.repos.run_event_repo.list(rig.owner, "expert", "two", include_archived=False)
    assert not rig.repos.workbench_repo.list(
        rig.owner, "expert", "two", "plan", include_archived=False
    )
    assert rig.repos.run_event_repo.get(rig.owner, "old-job")["status"] == "completed"
    assert len(rig.repos.run_event_repo.list(rig.owner, "expert", "two")) == 1
    assert len(rig.repos.workbench_repo.list(rig.owner, "expert", "two", "plan")) == 1


def test_ledger_archives_only_terminal_unscheduled_tasks(rig: Any) -> None:
    old = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    tasks = [
        BoardTask(id=identity, title=identity, status=status, created_at=old, updated_at=old)
        for identity, status in (
            ("done", "done"),
            ("failed", "failed"),
            ("draft", "planning"),
            ("repeat", "done"),
        )
    ]
    tasks[-1].schedule = Schedule(cron="0 * * * *", timezone="UTC", enabled=True)
    assert rig.repos.task_board_repo.save(
        rig.owner, 0, json.dumps({"tasks": [t.model_dump() for t in tasks]})
    )
    service = TaskBoardService(
        repos=rig.repos,
        timezone="UTC",
        registry=rig.manager,
        gateway=SimpleNamespace(),
        delivery=SimpleNamespace(),
    )
    service.archive_completed()
    snapshot = service.snapshot(rig.owner)
    assert {t.id for t in snapshot.tasks if t.archived} == {"done", "failed"}
    assert {t.id for t in snapshot.tasks if not t.archived} == {"draft", "repeat"}
    assert len(snapshot.tasks) == 4


def test_archive_schema_reconciles_an_already_recorded_watermark(rig: Any) -> None:
    with rig.pool.transaction() as conn:
        conn.execute("DROP TABLE task_history_archives")
    run_migrations(rig.pool)
    TaskArchiveRepo(rig.pool).archive_terminal()
    with rig.pool.connect() as conn:
        assert conn.execute("SELECT version FROM _schema_version").fetchone()[0] == 41


def test_api_schema_and_archive_filter_are_reviewable_without_llm(rig: Any) -> None:
    work(rig, "visible")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=rig.owner)
    app.dependency_overrides[get_server] = lambda: SimpleNamespace(
        app_runtime=SimpleNamespace(agent_registry=rig.manager)
    )
    with TestClient(app) as client:
        response = client.get("/task-center?agent_id=expert&lifecycle=active")
        assert response.status_code == 200
        assert response.json()["items"][0]["source_id"] == "visible"
        assert client.get("/task-center?limit=0").status_code == 422
        schema = client.get("/openapi.json").json()
        assert schema["paths"]["/task-center"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"].endswith("TaskOverviewPage")
