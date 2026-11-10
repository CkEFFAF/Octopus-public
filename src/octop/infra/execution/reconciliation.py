"""Refresh durable Job receipts independently of chats and browser polling."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from octop.infra.db.repos.run_events import RunEventRepo
from octop.infra.devices.service import DeviceService
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.execution.service import ExecutionService
from octop.infra.metrics import PERFORMANCE

if TYPE_CHECKING:
    from octop.infra.cron.manager import CronManager


class ExecutionReconciler:
    def __init__(self, devices: DeviceService, cron_manager: CronManager | None = None) -> None:
        self.devices = devices
        self.cron_manager = cron_manager
        self._running = False
        self._waking = False
        self._backoff: OrderedDict[tuple[int, str, str], tuple[int, float]] = OrderedDict()

    async def tick_wakeups(self) -> None:
        """Dispatch ready events independently of slow/offline Job observations."""
        if self.cron_manager is None or self._waking:
            return
        from octop.infra.execution.wakeup_hooks import WakeupHookService

        self._waking = True
        try:
            await WakeupHookService(ExecutionService(self.devices)).tick(self.cron_manager)
        finally:
            self._waking = False

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
            groups: dict[tuple[int, str, str], list[dict[str, Any]]] = {}
            for row in due:
                key = row["_poll_target"]
                groups.setdefault(key, []).append(row)

            async def observe(key: tuple[int, str, str], rows: list[dict[str, Any]]) -> None:
                failures, retry_at = self._backoff.get(key, (0, 0.0))
                if retry_at > time.monotonic():
                    return
                # One in-flight observation per target leaves capacity for other
                # devices even if one server has many unreachable Jobs.
                for row in rows:
                    async with capacity:
                        with PERFORMANCE.measure("job_observation"):
                            reachable = await self._observe(events, row)
                    if not reachable:
                        failures = min(failures + 1, 5)
                        delay = min(30 * 2 ** (failures - 1), 300)
                        self._backoff[key] = (failures, time.monotonic() + delay)
                        self._backoff.move_to_end(key)
                        while len(self._backoff) > 512:
                            self._backoff.popitem(last=False)
                        return
                    self._backoff.pop(key, None)
                    failures = 0

            await asyncio.gather(*(observe(key, rows) for key, rows in groups.items()))
            await self.tick_wakeups()
        finally:
            self._running = False

    async def _observe(self, events: RunEventRepo, row: dict[str, Any]) -> bool:
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
            return not (
                isinstance(exc, (OSError, TimeoutError))
                or isinstance(exc, OctopError)
                and exc.code == ErrorCode.DEVICE_OFFLINE
            )
        return True
