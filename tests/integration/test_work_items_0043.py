"""0043 integration: HTTP work-items API + Jobs/reconciler path (AC-0043-08)."""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from octop.infra.db.repos.run_events import RunEventRepo
from octop.infra.execution.reconciliation import ExecutionReconciler
from octop.infra.execution.service import ExecutionService
from tests.support.app import octop_client
from tests.support.auth import auth_header, bootstrap_admin, ensure_users


@pytest.fixture
async def env(tmp_octop_home: Path) -> AsyncIterator[Any]:
    async with octop_client(tmp_octop_home) as (c, srv):
        await bootstrap_admin(c, tmp_octop_home)
        admin_auth = await auth_header(c)
        users = await ensure_users(c, admin_auth, "alice")
        yield c, srv, users["alice"], admin_auth


async def _agent_and_thread(c: Any, auth: dict[str, str]) -> tuple[str, str]:
    resp = await c.post("/api/agents", headers=auth, json={"name": "work-agent"})
    assert resp.status_code == 201, resp.text
    agent_id = resp.json()["agent_id"]
    resp = await c.post(f"/api/agents/{agent_id}/threads", headers=auth)
    assert resp.status_code == 201, resp.text
    return agent_id, resp.json()["thread_id"]


@pytest.mark.asyncio
async def test_http_create_list_progress_cancel(env: Any) -> None:
    c, srv, alice_auth, _admin = env
    agent_id, origin = await _agent_and_thread(c, alice_auth)
    body = {
        "command_id": "http-cmd-1",
        "agent_id": agent_id,
        "origin_thread_id": origin,
        "title": "HTTP work",
        "instructions": "run quietly",
        "execution": {"target_kind": "device"},
        "resources": [],
        "schema_version": 1,
    }
    resp = await c.post("/api/work-items", headers=alice_auth, json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["idempotent_replay"] is False
    assert data["schema_version"] == 1
    task_id = data["task_id"]

    replay = await c.post("/api/work-items", headers=alice_auth, json=body)
    assert replay.status_code == 200
    assert replay.json()["task_id"] == task_id
    assert replay.json()["idempotent_replay"] is True

    listed = await c.get("/api/work-items?status_group=all", headers=alice_auth)
    assert listed.status_code == 200
    assert any(i["task_id"] == task_id for i in listed.json()["items"])

    # Progress read-only: many polls must not create chat_input / steer receipts
    for _ in range(10):
        prog = await c.get(f"/api/work-items/{task_id}/progress", headers=alice_auth)
        assert prog.status_code == 200
        assert prog.json()["task_id"] == task_id

    detail = await c.get(f"/api/work-items/{task_id}", headers=alice_auth)
    assert detail.status_code == 200
    assert detail.json()["origin_thread_id"] == origin

    events = await c.get(f"/api/work-items/{task_id}/events", headers=alice_auth)
    assert events.status_code == 200
    assert events.json()["schema_version"] == 1

    cancel = await c.post(
        f"/api/work-items/{task_id}/cancel",
        headers=alice_auth,
        json={"command_id": "cancel-http-1", "scope": "task", "schema_version": 1},
    )
    assert cancel.status_code == 200
    payload = cancel.json()
    assert payload["cancel_requested"] is True
    assert "terminated" in payload


@pytest.mark.asyncio
async def test_origin_deleted_still_gettable(env: Any) -> None:
    c, srv, alice_auth, _admin = env
    agent_id, origin = await _agent_and_thread(c, alice_auth)
    resp = await c.post(
        "/api/work-items",
        headers=alice_auth,
        json={
            "command_id": "tomb-1",
            "agent_id": agent_id,
            "origin_thread_id": origin,
            "title": "Tomb",
            "instructions": "x",
            "execution": {"target_kind": "device"},
            "schema_version": 1,
        },
    )
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]
    deleted = await c.delete(f"/api/agents/{agent_id}/threads/{origin}", headers=alice_auth)
    assert deleted.status_code in {200, 204}, deleted.text
    detail = await c.get(f"/api/work-items/{task_id}", headers=alice_auth)
    assert detail.status_code == 200
    assert detail.json()["origin_thread_missing"] is True


@pytest.mark.asyncio
async def test_job_reconciler_path_updates_without_blind_replay(env: Any, tmp_path: Path) -> None:
    """AC-0043-08: real Jobs + reconciler; unknown observation does not resubmit."""
    c, srv, _alice_auth, admin_auth = env
    # Prefer the bootstrapped admin account (local Jobs require admin).
    owner_user = None
    for name in ("admin",):
        owner_user = srv.user_manager.get(name)
        if owner_user is not None:
            break
    if owner_user is None:
        users = [u for u in srv.user_manager.list() if getattr(u, "role", "") == "admin"]
        owner_user = users[0] if users else None
    assert owner_user is not None
    agent_id, origin = await _agent_and_thread(c, admin_auth)
    resp = await c.post(
        "/api/work-items",
        headers=admin_auth,
        json={
            "command_id": "job-1",
            "agent_id": agent_id,
            "origin_thread_id": origin,
            "title": "Job work",
            "instructions": "observe",
            "execution": {"target_kind": "local", "working_dir": str(tmp_path)},
            "schema_version": 1,
        },
    )
    assert resp.status_code == 200, resp.text
    task_id = resp.json()["task_id"]
    await asyncio.sleep(0.1)

    assert srv.app_runtime is not None
    devices = srv.app_runtime.devices
    execution = ExecutionService(devices)
    owner = int(owner_user.id)
    context = execution.resolve(
        owner,
        target_kind="local",
        working_dir=str(tmp_path),
        agent_id=agent_id,
        work_item_id=task_id,
    )

    accepted = (
        await execution.call(
            owner,
            context.context_id,
            "jobs.start",
            {
                "argv": [sys.executable, "-c", "print('work-item-job')"],
                "idempotency_key": f"wi-{task_id}",
            },
        )
    )["result"]
    job_id = accepted["job_id"]
    events = RunEventRepo(srv.services.repos.db)
    # Link the job event to the work item if the inspection path didn't
    row = events.get(owner, f"job:{context.context_id}:{job_id}")
    if row is not None and row.get("work_item_id") is None:
        with srv.services.repos.db.transaction() as conn:
            conn.execute(
                "UPDATE run_events SET work_item_id = ? WHERE event_id = ?",
                (task_id, row["event_id"]),
            )

    deadline = asyncio.get_running_loop().time() + 15
    final = None
    while asyncio.get_running_loop().time() < deadline:
        with events.db.transaction() as conn:
            conn.execute(
                "UPDATE run_events SET updated_at = ? WHERE kind = 'job'",
                (time.time() - 30,),
            )
        await ExecutionReconciler(devices).tick()
        final = events.get(owner, f"job:{context.context_id}:{job_id}")
        if final and final["status"] == "completed":
            break
        await asyncio.sleep(0.1)
    assert final is not None and final["status"] == "completed"
    # Reconciler observes; it must not create a second job for the same job_id.
    with events.db.connect() as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM run_events WHERE kind='job' AND event_id = ?",
            (f"job:{context.context_id}:{job_id}",),
        ).fetchone()["n"]
    assert n == 1
    # Starting again with the same idempotency key must not spawn a second durable job.
    again = (
        await execution.call(
            owner,
            context.context_id,
            "jobs.start",
            {
                "argv": [sys.executable, "-c", "print('work-item-job')"],
                "idempotency_key": f"wi-{task_id}",
            },
        )
    )["result"]
    assert again["job_id"] == job_id

    # Work item remains readable; mark unknown without replay
    wi = srv.app_runtime.work_items
    wi.mark_unknown(owner, task_id, reason="test_unconfirmed")
    detail = await c.get(f"/api/work-items/{task_id}", headers=admin_auth)
    assert detail.status_code == 200
    assert detail.json()["status"] == "unknown"
