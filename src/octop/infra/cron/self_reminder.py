"""Agent session self-reminder helpers (0018 + 0042 origin_thread)."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

SELF_REMINDER_KIND = "self_reminder"
MAX_PURPOSE_LEN = 200
MAX_FIRES_DEFAULT_REPEAT = 3
MAX_FIRES_HARD_CAP = 20
MIN_REPEAT_SECONDS = 60

# Frozen meta keys (DEC-0042-01 / DEC-0042-10). origin_thread_id is write-once.
ORIGIN_THREAD_ID_KEY = "origin_thread_id"
ORIGIN_BOUND_AT_KEY = "origin_bound_at"
NEEDS_RETARGET_KEY = "needs_retarget"

ERR_ORIGIN_THREAD_MISSING = "origin_thread_missing"
ERR_ORIGIN_THREAD_UNAVAILABLE = "origin_thread_unavailable"
ERR_PERSIST_FAILED = "persist_failed"
ERR_DUPLICATE_DELIVERY = "duplicate_delivery"

logger = logging.getLogger(__name__)


def build_wakeup_prompt(*, purpose: str) -> str:
    purpose_clean = (purpose or "").strip()[:MAX_PURPOSE_LEN]
    return (
        "[SELF_CHECK_REMINDER]\n"
        f"purpose: {purpose_clean}\n"
        "You previously scheduled this self-check. Wall-clock time has been reached.\n"
        "1) Summarize progress since the last user-visible update (or say unknown).\n"
        "2) Detect if you are blocked or idle without a plan; if so, propose recovery.\n"
        "3) Report briefly to the user, then continue the task or ask one clarifying question.\n"
        "Do not create duplicate reminders unless still needed; cancel spent one-shot reminders."
    )


def resolve_fire_at(
    *,
    at: str | None = None,
    in_seconds: int | None = None,
    in_minutes: int | None = None,
    now: datetime | None = None,
) -> datetime:
    """Resolve wall-clock fire time. Exactly one of at / in_seconds / in_minutes required."""
    provided = sum(x is not None for x in (at, in_seconds, in_minutes))
    if provided != 1:
        raise ValueError("provide exactly one of at, in_seconds, or in_minutes")
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    if at is not None:
        text = at.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        fire = datetime.fromisoformat(text)
        if fire.tzinfo is None:
            fire = fire.replace(tzinfo=UTC)
        if fire <= now:
            raise ValueError("at must be in the future (wall-clock)")
        return fire.astimezone(UTC)
    if in_minutes is not None:
        if int(in_minutes) <= 0:
            raise ValueError("in_minutes must be positive")
        return now + timedelta(minutes=int(in_minutes))
    assert in_seconds is not None
    if int(in_seconds) <= 0:
        raise ValueError("in_seconds must be positive")
    return now + timedelta(seconds=int(in_seconds))


def build_trigger(
    *,
    fire_at: datetime,
    repeat_every_seconds: int | None = None,
) -> tuple[str, dict[str, Any]]:
    if repeat_every_seconds is not None:
        secs = int(repeat_every_seconds)
        if secs < MIN_REPEAT_SECONDS:
            raise ValueError(f"repeat_every_seconds must be >= {MIN_REPEAT_SECONDS}")
        meta = {
            "self_reminder": True,
            "max_fires": MAX_FIRES_DEFAULT_REPEAT,
            "fires": 0,
        }
        return f"interval:{secs}", meta
    meta = {"self_reminder": True, "max_fires": 1, "fires": 0}
    iso = fire_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return f"date:{iso}", meta


def is_self_reminder_row(row: Any) -> bool:
    kind = getattr(row, "kind", None)
    if kind == SELF_REMINDER_KIND:
        return True
    meta = getattr(row, "meta", None) or {}
    return isinstance(meta, dict) and meta.get("self_reminder") is True


def encode_meta(meta: dict[str, Any] | None) -> str:
    import json

    return json.dumps(meta or {}, ensure_ascii=False)


def decode_meta(raw: Any) -> dict[str, Any]:
    import json

    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def origin_thread_id(meta: dict[str, Any] | None) -> str | None:
    """Return frozen origin_thread_id when present and non-empty."""
    if not isinstance(meta, dict):
        return None
    value = meta.get(ORIGIN_THREAD_ID_KEY)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def needs_retarget(meta: dict[str, Any] | None) -> bool:
    return bool(isinstance(meta, dict) and meta.get(NEEDS_RETARGET_KEY) is True)


def stamp_origin_meta(
    meta: dict[str, Any] | None,
    *,
    thread_id: str,
    bound_at: int | None = None,
) -> dict[str, Any]:
    """Deep-merge immutable origin binding. Existing origin_thread_id is never overwritten."""
    out = dict(meta or {})
    tid = (thread_id or "").strip()
    if not tid:
        raise ValueError("origin_thread_id must be non-empty")
    existing = origin_thread_id(out)
    if existing:
        # Immutable after create (DEC-0042-01).
        return out
    out[ORIGIN_THREAD_ID_KEY] = tid
    out[ORIGIN_BOUND_AT_KEY] = int(bound_at if bound_at is not None else time.time())
    out[NEEDS_RETARGET_KEY] = False
    return out


def mark_needs_retarget(meta: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(meta or {})
    out[NEEDS_RETARGET_KEY] = True
    return out


def preserve_origin_keys(
    existing: dict[str, Any] | None, incoming: dict[str, Any]
) -> dict[str, Any]:
    """Merge meta updates without allowing origin_thread_id to change once set."""
    out = dict(incoming)
    prior = origin_thread_id(existing)
    if prior:
        out[ORIGIN_THREAD_ID_KEY] = prior
        if ORIGIN_BOUND_AT_KEY in (existing or {}):
            out[ORIGIN_BOUND_AT_KEY] = (existing or {}).get(ORIGIN_BOUND_AT_KEY)
        # needs_retarget may still flip true for ops; keep false if origin is bound
        if out.get(NEEDS_RETARGET_KEY) is not True:
            out[NEEDS_RETARGET_KEY] = False
    return out


def backfill_origin_from_session(
    row: Any,
    *,
    session_repo: Any,
    thread_repo: Any,
) -> tuple[str | None, dict[str, Any], str | None]:
    """Resolve origin_thread_id for a self-reminder row.

    Returns ``(origin_thread_id, meta, error_code)``.
    - When origin is present: validated against thread ownership.
    - When missing: backfill only if session_key maps to a unique matching thread.
    - Otherwise mark needs_retarget and return ``origin_thread_missing``.
    """
    meta = decode_meta(getattr(row, "meta", None))
    if needs_retarget(meta) and not origin_thread_id(meta):
        return None, meta, ERR_ORIGIN_THREAD_MISSING

    existing = origin_thread_id(meta)
    agent_id = str(getattr(row, "agent_id", "") or "")
    user_id = int(getattr(row, "user_id", 0) or 0)

    if existing:
        thread = thread_repo.get(existing)
        if thread is None:
            return None, meta, ERR_ORIGIN_THREAD_UNAVAILABLE
        if str(thread.agent_id) != agent_id or int(thread.user_id) != user_id:
            return None, meta, ERR_ORIGIN_THREAD_UNAVAILABLE
        return existing, meta, None

    session_key = str(getattr(row, "session_key", "") or "")
    if not session_key:
        meta = mark_needs_retarget(meta)
        return None, meta, ERR_ORIGIN_THREAD_MISSING

    session = session_repo.get(session_key)
    if session is None:
        meta = mark_needs_retarget(meta)
        return None, meta, ERR_ORIGIN_THREAD_MISSING

    if str(session.agent_id) != agent_id or int(session.user_id) != user_id:
        meta = mark_needs_retarget(meta)
        return None, meta, ERR_ORIGIN_THREAD_MISSING

    tid = str(session.thread_id or "").strip()
    if not tid:
        meta = mark_needs_retarget(meta)
        return None, meta, ERR_ORIGIN_THREAD_MISSING

    thread = thread_repo.get(tid)
    if thread is None:
        meta = mark_needs_retarget(meta)
        return None, meta, ERR_ORIGIN_THREAD_MISSING
    if str(thread.agent_id) != agent_id or int(thread.user_id) != user_id:
        meta = mark_needs_retarget(meta)
        return None, meta, ERR_ORIGIN_THREAD_MISSING

    # Unique proven target from the stored session_key binding → backfill.
    meta = stamp_origin_meta(meta, thread_id=tid)
    logger.info(
        "self_reminder backfilled origin_thread_id=%s cron_id=%s",
        tid,
        getattr(row, "cron_id", "?"),
    )
    return tid, meta, None


__all__ = [
    "ERR_DUPLICATE_DELIVERY",
    "ERR_ORIGIN_THREAD_MISSING",
    "ERR_ORIGIN_THREAD_UNAVAILABLE",
    "ERR_PERSIST_FAILED",
    "MAX_FIRES_DEFAULT_REPEAT",
    "MAX_FIRES_HARD_CAP",
    "MAX_PURPOSE_LEN",
    "MIN_REPEAT_SECONDS",
    "NEEDS_RETARGET_KEY",
    "ORIGIN_BOUND_AT_KEY",
    "ORIGIN_THREAD_ID_KEY",
    "SELF_REMINDER_KIND",
    "backfill_origin_from_session",
    "build_trigger",
    "build_wakeup_prompt",
    "decode_meta",
    "encode_meta",
    "is_self_reminder_row",
    "mark_needs_retarget",
    "needs_retarget",
    "origin_thread_id",
    "preserve_origin_keys",
    "resolve_fire_at",
    "stamp_origin_meta",
]
