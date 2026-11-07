"""Account-scoped ``thread.changed`` events for dashboard notification sockets (0041).

Single helper for Gateway / 0042 / G3. Emits opaque ids only — never tokens,
credentials, or message bodies. Failures are logged; callers must not roll back.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

from octop.infra.utils.ulid import new_ulid

logger = logging.getLogger(__name__)

THREAD_CHANGED_TYPE = "thread.changed"
THREAD_CHANGED_SCHEMA_VERSION = 1
THREAD_CHANGED_REASONS = frozenset(
    {
        "created",
        "input",
        "running",
        "attention",
        "completed",
        "failed",
        "cancelled",
    }
)
_TERMINAL_REASONS = frozenset({"completed", "failed", "cancelled"})
_RUNNING_MIN_INTERVAL_S = 1.0


class _UserPushHub(Protocol):
    async def push_to_user(self, user_id: int, frame: dict[str, Any]) -> None: ...


class ThreadEventEmitter:
    """Fan ``thread.changed`` frames to an owner via ``WebSocketHub.push_to_user``."""

    def __init__(self, hub: _UserPushHub) -> None:
        self._hub = hub
        # thread_id -> (monotonic last emit, phase key used for coalesce)
        self._running_last: dict[str, tuple[float, str]] = {}
        self._last_event_at: dict[str, float] = {}
        self._suppressed: set[str] = set()

    def suppress_thread(self, thread_id: str) -> None:
        """Stop further emits after delete / revoke (DEC-0041-09)."""
        tid = thread_id.strip()
        if not tid:
            return
        self._suppressed.add(tid)
        self._running_last.pop(tid, None)
        self._last_event_at.pop(tid, None)

    def last_event_at(self, thread_id: str) -> float | None:
        return self._last_event_at.get(thread_id.strip())

    async def emit_thread_changed(
        self,
        *,
        owner_user_id: int,
        agent_id: str,
        thread_id: str,
        reason: str,
        run_id: str | None = None,
        updated_at: float | None = None,
        phase: str | None = None,
    ) -> None:
        """Push one account notification frame; best-effort, never raises to callers.

        ``phase`` is optional coalesce metadata for ``running`` only and is never
        placed on the wire frame.
        """
        tid = thread_id.strip()
        aid = agent_id.strip()
        if not tid or not aid:
            return
        if tid in self._suppressed:
            return
        if reason not in THREAD_CHANGED_REASONS:
            logger.warning("thread.changed: unknown reason %r thread=%s", reason, tid)
            return
        try:
            if reason == "running" and not self._should_emit_running(tid, phase):
                return
            ts = float(time.time() if updated_at is None else updated_at)
            frame: dict[str, Any] = {
                "type": THREAD_CHANGED_TYPE,
                "event_id": self._event_id(tid, reason, phase=phase, updated_at=ts),
                "agent_id": aid,
                "thread_id": tid,
                "run_id": run_id,
                "reason": reason,
                "updated_at": ts,
                "schema_version": THREAD_CHANGED_SCHEMA_VERSION,
            }
            await self._hub.push_to_user(int(owner_user_id), frame)
            self._last_event_at[tid] = ts
            if reason in _TERMINAL_REASONS:
                self._running_last.pop(tid, None)
        except Exception:
            logger.exception(
                "thread.changed push failed owner=%s thread=%s reason=%s",
                owner_user_id,
                tid,
                reason,
            )

    def _should_emit_running(self, thread_id: str, phase: str | None) -> bool:
        now = time.monotonic()
        phase_key = (phase or "").strip() or "_"
        prev = self._running_last.get(thread_id)
        if prev is not None:
            last_mono, last_phase = prev
            if phase_key == last_phase and (now - last_mono) < _RUNNING_MIN_INTERVAL_S:
                return False
        self._running_last[thread_id] = (now, phase_key)
        return True

    @staticmethod
    def _event_id(
        thread_id: str,
        reason: str,
        *,
        phase: str | None,
        updated_at: float,
    ) -> str:
        if reason == "running":
            # Stable within the coalesce bucket (1s) for client dedupe (DEC-0041-11).
            bucket = int(updated_at)
            phase_key = (phase or "").strip() or "_"
            return f"tc:{thread_id}:running:{phase_key}:{bucket}"
        return new_ulid()


def build_turn_status_frame(
    *,
    thread_id: str,
    active: bool,
    steering: dict[str, Any] | None,
    input_controls: bool = True,
    last_event_at: float | None = None,
    active_tools: list[str] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Extend the existing ``turn_status`` snapshot (DEC-0041-08); omit unknowns."""
    runtime: dict[str, Any] | None = None
    if isinstance(steering, dict):
        runtime = {}
        phase = steering.get("phase")
        run_id = steering.get("run_id")
        if phase is not None:
            runtime["phase"] = phase
        if run_id is not None:
            runtime["run_id"] = run_id
        if active_tools:
            runtime["active_tools"] = [str(n) for n in active_tools if str(n).strip()]
        if last_event_at is not None:
            runtime["last_event_at"] = last_event_at
        if not runtime:
            runtime = None
    elif last_event_at is not None:
        runtime = {"last_event_at": last_event_at}

    frame: dict[str, Any] = {
        "type": "turn_status",
        "thread_id": thread_id,
        "active": bool(active),
        "runtime": runtime,
        "input_controls": bool(input_controls),
        "schema_version": THREAD_CHANGED_SCHEMA_VERSION,
    }
    if artifacts:
        safe: list[dict[str, Any]] = []
        for item in artifacts:
            if not isinstance(item, dict):
                continue
            rid = item.get("resource_id")
            ver = item.get("version")
            if isinstance(rid, str) and rid.strip() and ver is not None:
                safe.append({"resource_id": rid.strip(), "version": ver})
        if safe:
            frame["artifacts"] = safe
    return frame


__all__ = [
    "THREAD_CHANGED_REASONS",
    "THREAD_CHANGED_SCHEMA_VERSION",
    "THREAD_CHANGED_TYPE",
    "ThreadEventEmitter",
    "build_turn_status_frame",
]
