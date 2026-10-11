"""AC-03/07: cancellation and reconnect keep the durable device ledger truthful."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.devices.service import DeviceService
from octop.infra.errors import OctopError


@pytest_asyncio.fixture
async def device_rig(tmp_path: Path) -> AsyncIterator[Any]:
    pool = SqlitePool(tmp_path / "device-lifecycle.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="owner", role="admin", password_hash="test")
    service = DeviceService(repos)
    enrolled = service.enroll(
        pairing_code=service.pairing(owner)["pairing_code"],
        name="Lifecycle device",
        platform="windows",
        capabilities=[],
        permissions=[],
        roots=[],
    )
    sent = asyncio.Event()
    requests: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        if frame["type"] == "request":
            requests.append(frame)
            sent.set()

    async def close() -> None:
        return None

    device_id = enrolled["device"]["device_id"]
    connection = await service.connect(device_id, enrolled["device_token"], send, close)
    try:
        yield SimpleNamespace(
            service=service,
            owner=owner,
            device_id=device_id,
            token=enrolled["device_token"],
            connection=connection,
            send=send,
            close=close,
            sent=sent,
            requests=requests,
            repos=repos,
        )
    finally:
        await service.shutdown()
        pool.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupt", ["cancel", "revoke"])
async def test_interrupt_before_dispatch_settles_queued_operation(
    device_rig: Any, interrupt: str
) -> None:
    rig = device_rig
    operation = rig.service.submit(
        rig.owner, rig.device_id, "ping", {}, task_run_id="interrupted-run"
    )
    jobs = list(rig.service._jobs.values())
    # No yield between submission and interruption: the operation cannot have started.
    if interrupt == "cancel":
        returned = await rig.service.cancel(rig.owner, operation["operation_id"])
        assert returned["status"] in {"cancelled", "unknown"}
    else:
        await rig.service.revoke(rig.owner, rig.device_id)
    await asyncio.gather(*jobs, return_exceptions=True)

    persisted = rig.service.operation(rig.owner, operation["operation_id"])
    assert persisted.status in {"cancelled", "unknown"}
    assert rig.requests == []
    # A task must fail promptly, rather than waiting forever on an orphan queued row.
    with pytest.raises(OctopError):
        await asyncio.wait_for(
            rig.service.wait_for_task_run(rig.owner, "interrupted-run"), timeout=0.5
        )


@pytest.mark.asyncio
async def test_reconciled_completion_survives_old_connection_failure(device_rig: Any) -> None:
    rig = device_rig
    operation = rig.service.submit(rig.owner, rig.device_id, "ping", {})
    await asyncio.wait_for(rig.sent.wait(), timeout=2)
    jobs = list(rig.service._jobs.values())

    rig.service.disconnect(rig.connection)
    fresh = await rig.service.connect(rig.device_id, rig.token, rig.send, rig.close)
    receipt = {"platform": "windows", "hostname": "device", "capabilities": []}
    # Reconciliation arrives before the old dispatch coroutine processes disconnection.
    await rig.service.receive(
        fresh,
        {
            "type": "reconcile",
            "results": [{"id": operation["operation_id"], "ok": True, "result": receipt}],
        },
    )
    await asyncio.gather(*jobs, return_exceptions=True)

    persisted = rig.service.operation(rig.owner, operation["operation_id"])
    assert persisted.status == "completed"
    assert persisted.result == receipt
    assert persisted.error is None
    assert len(rig.requests) == 1  # Reconnect must never replay the operation.
