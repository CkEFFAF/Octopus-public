"""Refresh durable Job receipts independently of chats and browser polling."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from octop.infra.db.repos.run_events import RunEventRepo
from octop.infra.devices.service import DeviceService
from octop.infra.errors import OctopError
from octop.infra.execution.service import ExecutionService


class ExecutionReconciler:
    def __init__(self, devices: DeviceService) -> None:
        self.devices = devices
        self._running = False

    async def tick(self) -> None:
        if self._running:
            return
        self._running = True
        try:
            local = self.devices.local_execution
            if local is not None:
                for owner in local.owners:
                    user = self.devices.repos.user_repo.get(owner)
                    if user is None or user.disabled or user.role != "admin":
                        await local.revoke(owner)
            events = RunEventRepo(self.devices.repos.db)
            due = events.due_jobs(time.time() - 15)
            capacity = asyncio.Semaphore(4)

            async def observe(row: dict[str, Any]) -> None:
                async with capacity:
                    await self._observe(events, row)

            await asyncio.gather(*(observe(row) for row in due))
        finally:
            self._running = False

    async def _observe(self, events: RunEventRepo, row: dict[str, Any]) -> None:
        owner, payload = int(row["owner_user_id"]), row["payload"]
        try:
            # Reauthorize the original frozen target. Never resubmit a command,
            # select another device or weaken a stale policy to obtain a status.
            async with asyncio.timeout(8):
                await ExecutionService(self.devices).call(
                    owner, row["context_id"], "jobs.status", {"job_id": payload["job_id"]}
                )
        except (OctopError, OSError, TimeoutError, KeyError) as exc:
            events.compare_payload(
                owner,
                row["event_id"],
                payload,
                {
                    **payload,
                    "observation": {
                        "status": "unavailable",
                        "checked_at": time.time(),
                        "error_code": exc.code.value
                        if isinstance(exc, OctopError)
                        else type(exc).__name__,
                    },
                },
                row["status"],
            )
