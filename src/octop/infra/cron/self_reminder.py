"""Agent session self-reminder helpers (0018). Distinct from product cron UX."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

SELF_REMINDER_KIND = "self_reminder"
MAX_PURPOSE_LEN = 200
MAX_FIRES_DEFAULT_REPEAT = 3
MAX_FIRES_HARD_CAP = 20
MIN_REPEAT_SECONDS = 60


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


__all__ = [
    "MAX_FIRES_DEFAULT_REPEAT",
    "MAX_FIRES_HARD_CAP",
    "MAX_PURPOSE_LEN",
    "MIN_REPEAT_SECONDS",
    "SELF_REMINDER_KIND",
    "build_trigger",
    "build_wakeup_prompt",
    "decode_meta",
    "encode_meta",
    "is_self_reminder_row",
    "resolve_fire_at",
]
