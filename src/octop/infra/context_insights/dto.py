"""Shared Context Insights DTO helpers (0021 DEC-T02 / T05 / T15)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

SCHEMA_VERSION = "2026-10-16.3"

CoverageLevel = Literal["complete", "partial", "unavailable"]


def utc_rfc3339(ts: float | None = None) -> str:
    """UTC RFC3339 timestamp; wall clock when *ts* omitted."""
    moment = datetime.now(UTC) if ts is None else datetime.fromtimestamp(float(ts), tz=UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def coverage_block(
    *,
    level: CoverageLevel,
    observed_start: int | None = None,
    observed_head: int | None = None,
    queried_range: dict[str, Any] | None = None,
    missing_ranges: list[dict[str, Any]] | None = None,
    reason_codes: list[str] | None = None,
    next_cursor: str | int | None = None,
    source: str | None = None,
    quality: str | None = None,
) -> dict[str, Any]:
    """Minimal coverage envelope; unknown ≠ 0 (DEC-T05)."""
    return {
        "coverage": level,
        "observed_start": observed_start,
        "observed_head": observed_head,
        "queried_range": queried_range,
        "missing_ranges": list(missing_ranges or []),
        "reason_codes": list(reason_codes or []),
        "next_cursor": next_cursor,
        "source": source,
        "quality": quality,
    }


def resolved_scope(
    *,
    owner_user_id: int,
    agent_id: str,
    thread_id: str,
    readable: bool = True,
) -> dict[str, Any]:
    """Minimal single-session ResolvedContextScope (DEC-T02)."""
    return {
        "subject": {"owner_user_id": owner_user_id},
        "agent_id": agent_id,
        "thread_id": thread_id,
        "readable_threads": [thread_id] if readable else [],
        "capabilities": ["inspect", "events", "file_ops", "request", "trace_read"]
        if readable
        else [],
        "room_ref": None,
        "admission": {"mode": "owner_thread", "shared": False},
    }


def source_ref(source: str, ref_id: str) -> dict[str, str]:
    return {"source": source, "id": ref_id}
