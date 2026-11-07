"""Account-scoped ``task.changed`` events for dashboard notification sockets (0043).

Companion to ``thread_events.py``. Same ``push_to_user`` hub; never tokens,
credentials, or full instructions. Failures are logged; callers must not roll back.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

from octop.infra.utils.ulid import new_ulid
from octop.infra.work_items.models import TASK_CHANGED_REASONS

logger = logging.getLogger(__name__)

TASK_CHANGED_TYPE = "task.changed"
TASK_CHANGED_SCHEMA_VERSION = 1
_PROGRESS_MIN_INTERVAL_S = 1.0
_TERMINAL_REASONS = frozenset({"completed", "failed", "cancelled", "unknown"})


class _UserPushHub(Protocol):
    async def push_to_user(self, user_id: int, frame: dict[str, Any]) -> None: ...


class TaskEventEmitter:
    """Fan ``task.changed`` frames to an owner via ``WebSocketHub.push_to_user``."""

    def __init__(self, hub: _UserPushHub) -> None:
        self._hub = hub
        self._progress_last: dict[str, tuple[float, str]] = {}
        self._suppressed_owners: set[int] = set()

    def suppress_owner(self, owner_user_id: int) -> None:
        """Stop further emits after user disable (DEC-0043-08)."""
        self._suppressed_owners.add(int(owner_user_id))

    def clear_suppress(self, owner_user_id: int) -> None:
        self._suppressed_owners.discard(int(owner_user_id))

    async def emit_task_changed(
        self,
        *,
        owner_user_id: int,
        task_id: str,
        agent_id: str,
        reason: str,
        status: str,
        origin_thread_id: str | None = None,
        run_id: str | None = None,
        updated_at: float | None = None,
        phase: str | None = None,
    ) -> None:
        tid = task_id.strip()
        aid = agent_id.strip()
        if not tid or not aid:
            return
        if int(owner_user_id) in self._suppressed_owners:
            return
        if reason not in TASK_CHANGED_REASONS:
            logger.warning("task.changed: unknown reason %r task=%s", reason, tid)
            return
        try:
            if reason == "progress" and not self._should_emit_progress(tid, phase):
                return
            ts = float(time.time() if updated_at is None else updated_at)
            frame: dict[str, Any] = {
                "type": TASK_CHANGED_TYPE,
                "event_id": self._event_id(tid, reason, phase=phase, updated_at=ts),
                "task_id": tid,
                "agent_id": aid,
                "origin_thread_id": origin_thread_id,
                "run_id": run_id,
                "reason": reason,
                "status": status,
                "updated_at": ts,
                "schema_version": TASK_CHANGED_SCHEMA_VERSION,
            }
            await self._hub.push_to_user(int(owner_user_id), frame)
            if reason in _TERMINAL_REASONS:
                self._progress_last.pop(tid, None)
        except Exception:
            logger.exception(
                "task.changed push failed owner=%s task=%s reason=%s",
                owner_user_id,
                tid,
                reason,
            )

    def _should_emit_progress(self, task_id: str, phase: str | None) -> bool:
        now = time.monotonic()
        phase_key = (phase or "").strip() or "_"
        prev = self._progress_last.get(task_id)
        if prev is not None:
            last_mono, last_phase = prev
            if phase_key == last_phase and (now - last_mono) < _PROGRESS_MIN_INTERVAL_S:
                return False
        self._progress_last[task_id] = (now, phase_key)
        return True

    @staticmethod
    def _event_id(
        task_id: str,
        reason: str,
        *,
        phase: str | None,
        updated_at: float,
    ) -> str:
        if reason == "progress":
            bucket = int(updated_at)
            phase_key = (phase or "").strip() or "_"
            return f"tk:{task_id}:progress:{phase_key}:{bucket}"
        return new_ulid()


__all__ = [
    "TASK_CHANGED_SCHEMA_VERSION",
    "TASK_CHANGED_TYPE",
    "TaskEventEmitter",
]
