"""Controller observations survive service recreation and never replay Jobs."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.run_events import RunEventRepo
from octop.infra.db.services import RepoBundle
from octop.infra.devices.service import DeviceService
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.execution.events import RunInspectionService
from octop.infra.execution.reconciliation import ExecutionReconciler
from octop.infra.execution.service import ExecutionService


@pytest.fixture
async def hub(tmp_path: Path) -> Any:
    pool = SqlitePool(tmp_path / "hub.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="owner", role="admin", password_hash="unused")
    repos.agent_repo.create(agent_id="expert", user_id=owner, name="Expert")
    repos.thread_repo.insert(
        thread_id="thread",
        agent_id="expert",
        user_id=owner,
        channel_type="dashboard",
        session_key="test",
    )
    devices = DeviceService(repos, local_state_dir=tmp_path / "runtime")
    service = ExecutionService(devices)
    context = service.resolve(
        owner,
        target_kind="local",
        working_dir=str(tmp_path),
        agent_id="expert",
        thread_id="thread",
    )
    yield service, context, RunEventRepo(pool), tmp_path
    if devices.local_execution:
        for runtime in devices.local_execution._runtimes.values():
            await asyncio.to_thread(runtime.stop_jobs)
    await devices.shutdown()
    pool.close()


def age(events: RunEventRepo) -> None:
    with events.db.transaction() as conn:
        conn.execute("UPDATE run_events SET updated_at = ? WHERE kind = 'job'", (time.time() - 30,))


async def test_refreshes_real_completed_job_without_browser_and_recovers_index(hub: Any) -> None:
    service, context, events, root = hub
    accepted = (
        await service.call(
            context.owner_user_id,
            context.context_id,
            "jobs.start",
            {
                "argv": [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path('once').open('a').write('x')",
                ],
                "idempotency_key": "reconcile-once",
            },
        )
    )["result"]
    job_id = accepted["job_id"]
    assert accepted["status"] in {"queued", "running"}
    # Recreate the controller observer on every tick, as after a hub restart.
    deadline = asyncio.get_running_loop().time() + 15
    while asyncio.get_running_loop().time() < deadline:
        age(events)
        await ExecutionReconciler(service.devices).tick()
        row = events.get(context.owner_user_id, f"job:{context.context_id}:{job_id}")
        if row["status"] == "completed":
            break
        await asyncio.sleep(0.1)
    assert row["status"] == "completed" and row["payload"]["returncode"] == 0
    assert (root / "once").read_text() == "x"
    reopened = service.resolve(context.owner_user_id, target_kind="local", working_dir=str(root))
    await service.call(context.owner_user_id, reopened.context_id, "jobs.list", {})
    with events.db.connect() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM run_events WHERE kind = 'job'").fetchone()["n"]
            == 1
        )


async def test_failed_observation_preserves_last_receipt_and_never_falls_back(hub: Any) -> None:
    service, context, events, _ = hub
    RunInspectionService(service.devices.repos).job_observation(
        context,
        {
            "job_id": "offline-job",
            "status": "running",
            "observed_at": 123,
        },
    )
    age(events)
    unavailable = AsyncMock(side_effect=OctopError(ErrorCode.DEVICE_OFFLINE, "offline"))
    with patch.object(ExecutionService, "call", unavailable):
        await ExecutionReconciler(service.devices).tick()
    unavailable.assert_awaited_once_with(
        context.owner_user_id, context.context_id, "jobs.status", {"job_id": "offline-job"}
    )
    row = events.get(context.owner_user_id, f"job:{context.context_id}:offline-job")
    assert row["status"] == "running" and row["payload"]["observed_at"] == 123
    assert row["payload"]["observation"]["status"] == "unavailable"
    assert row["payload"]["observation"]["error_code"] == ErrorCode.DEVICE_OFFLINE.value
    assert not events.due_jobs(time.time() - 15)


async def test_role_revocation_stops_host_job_without_another_user_request(hub: Any) -> None:
    service, context, events, _ = hub
    accepted = (
        await service.call(
            context.owner_user_id,
            context.context_id,
            "jobs.start",
            {
                "argv": [sys.executable, "-c", "import time; time.sleep(60)"],
                "idempotency_key": "stop-after-role-loss",
            },
        )
    )["result"]
    runtime = service.devices.local_execution.runtime(context.owner_user_id)
    service.devices.repos.user_repo.set_role(context.owner_user_id, "user")
    await ExecutionReconciler(service.devices).tick()
    assert context.owner_user_id not in service.devices.local_execution.owners
    assert not runtime.permissions
    deadline = asyncio.get_running_loop().time() + 10
    while asyncio.get_running_loop().time() < deadline:
        result = runtime._job_supervisor.status(accepted["job_id"])
        if result["status"] == "cancelled":
            break
        await asyncio.sleep(0.1)
    assert result["status"] == "cancelled"


async def test_detached_real_process_job_remains_visible_after_parent_exit(hub: Any) -> None:
    from types import SimpleNamespace

    from octop.infra.execution.activity import ActivityService

    service, context, events, root = hub
    owner = context.owner_user_id
    accepted = (
        await service.call(
            owner,
            context.context_id,
            "jobs.start",
            {
                "argv": [sys.executable, "-c", "import time; time.sleep(20)"],
                "idempotency_key": "detached-0034",
            },
        )
    )["result"]
    deadline = asyncio.get_running_loop().time() + 10
    while asyncio.get_running_loop().time() < deadline:
        age(events)
        await ExecutionReconciler(service.devices).tick()
        row = events.get(owner, f"job:{context.context_id}:{accepted['job_id']}")
        if row["status"] == "running":
            break
        await asyncio.sleep(0.05)
    manager = SimpleNamespace(
        _repos=service.devices.repos,
        _device_service=service.devices,
        steering_status=lambda agent, thread: None,
    )
    snapshot = ActivityService(manager).snapshot(owner, "expert", "thread")
    node = next(n for n in snapshot["nodes"] if n["type"] == "job")
    assert node["status"] == "running" and node["observed_status"] == "current"
    assert snapshot["counts"]["jobs"] == 1
    await service.call(owner, context.context_id, "jobs.cancel", {"job_id": accepted["job_id"]})
