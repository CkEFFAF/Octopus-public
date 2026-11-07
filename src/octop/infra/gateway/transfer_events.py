"""Account-scoped ``transfer.changed`` events for dashboard notification sockets (0044).

Opaque ids + status/transport/progress only — never paths, tickets, or tokens.
Failures are logged; callers must not roll back.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

from octop.infra.utils.ulid import new_ulid

logger = logging.getLogger(__name__)

TRANSFER_CHANGED_TYPE = "transfer.changed"
TRANSFER_CHANGED_SCHEMA_VERSION = 1
_PROGRESS_MIN_INTERVAL_S = 1.0
_TERMINAL = frozenset({"completed", "failed", "cancelled", "unknown"})


class _UserPushHub(Protocol):
    async def push_to_user(self, user_id: int, frame: dict[str, Any]) -> None: ...


class TransferEventEmitter:
    """Fan ``transfer.changed`` frames via ``WebSocketHub.push_to_user``."""

    def __init__(self, hub: _UserPushHub) -> None:
        self._hub = hub
        self._progress_last: dict[str, float] = {}

    async def emit_transfer_changed(
        self,
        *,
        owner_user_id: int,
        transfer_id: str,
        status: str,
        actual_transport: str | None = None,
        bytes_total: int | None = None,
        bytes_done: int | None = None,
        fallback_reason: str | None = None,
        updated_at: float | None = None,
    ) -> None:
        tid = transfer_id.strip()
        if not tid:
            return
        try:
            ts = float(time.time() if updated_at is None else updated_at)
            if status == "transferring" and not self._should_emit_progress(tid):
                return
            frame: dict[str, Any] = {
                "type": TRANSFER_CHANGED_TYPE,
                "event_id": new_ulid(),
                "transfer_id": tid,
                "status": status,
                "actual_transport": actual_transport,
                "bytes_total": bytes_total,
                "bytes_done": bytes_done,
                "fallback_reason": fallback_reason,
                "updated_at": ts,
                "schema_version": TRANSFER_CHANGED_SCHEMA_VERSION,
            }
            await self._hub.push_to_user(int(owner_user_id), frame)
            if status in _TERMINAL:
                self._progress_last.pop(tid, None)
        except Exception:
            logger.exception(
                "transfer.changed push failed owner=%s transfer=%s status=%s",
                owner_user_id,
                tid,
                status,
            )

    def _should_emit_progress(self, transfer_id: str) -> bool:
        now = time.monotonic()
        prev = self._progress_last.get(transfer_id)
        if prev is not None and (now - prev) < _PROGRESS_MIN_INTERVAL_S:
            return False
        self._progress_last[transfer_id] = now
        return True


__all__ = [
    "TRANSFER_CHANGED_SCHEMA_VERSION",
    "TRANSFER_CHANGED_TYPE",
    "TransferEventEmitter",
]
