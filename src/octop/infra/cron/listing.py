"""Authorized, ordered pages for the cross-expert schedule browser."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from octop.infra.cron.trigger import AgentlyMailTrigger, build_trigger
from octop.infra.errors import OctopError


def _thread_title(repos: Any, value: dict[str, Any], user_id: int) -> str | None:
    thread = repos.thread_repo.get(value["thread_id"]) if value["thread_id"] else None
    return (
        thread.title
        if thread and (thread.agent_id, thread.user_id) == (value["agent_id"], user_id)
        else None
    )


def schedule_category(value: dict[str, Any]) -> str:
    if value["scheduler_state"] in {"exhausted", "ended"}:
        return "ended"
    return "once" if value["trigger"].startswith("date:") else "repeat"


def schedule_lifecycle(value: dict[str, Any]) -> str:
    if value["scheduler_state"] in {"running", "scheduled", "waiting_event"}:
        return "active"
    if value.get("last_status") == "error":
        return "failed"
    if value["scheduler_state"] in {"exhausted", "ended"}:
        return "completed"
    return "inactive"


def schedule_frequency(trigger: str, timezone: str, now: datetime) -> float:
    """Compare recurring schedules by the gap between their next two fires."""
    try:
        parsed = build_trigger(trigger, timezone=timezone)
        if isinstance(parsed, AgentlyMailTrigger):
            return float("inf")
        first = parsed.get_next_fire_time(None, now)
        second = parsed.get_next_fire_time(first, first) if first else None
        return (second - first).total_seconds() if first and second else float("inf")
    except OctopError:
        return float("inf")


def list_schedule_page(
    manager: Any,
    *,
    repos: Any,
    timezone: str,
    user_id: int,
    agent_id: str | None,
    thread_id: str | None,
    reminder: bool | None,
    category: str | None,
    search: str,
    offset: int,
    limit: int,
    lifecycle: str | None = None,
) -> dict[str, Any]:
    agents = repos.agent_repo.list_by_user(user_id)
    now = datetime.now(UTC)
    values = []
    query = search.strip().casefold()
    for agent in agents:
        if agent_id is not None and agent.agent_id != agent_id:
            continue
        for row in manager.list_by_agent(
            agent.agent_id, user_id=user_id, include_self_reminders=True
        ):
            value = manager.public_view(row)
            if thread_id is not None and value["thread_id"] != thread_id:
                continue
            value["category"] = schedule_category(value)
            value["agent_name"] = agent.name
            if query:
                value["thread_title"] = _thread_title(repos, value, user_id)
            if (
                query
                and query
                not in " ".join(
                    [
                        agent.name,
                        value["name"],
                        value["prompt"],
                        value["thread_id"] or "",
                        value.get("thread_title") or "",
                    ]
                ).casefold()
            ):
                continue
            values.append(value)
    counts = {
        "schedules": sum(not value["self_reminder"] for value in values),
        "reminders": sum(bool(value["self_reminder"]) for value in values),
    }
    values = [
        value
        for value in values
        if (reminder is None or bool(value["self_reminder"]) == reminder)
        and (
            category is None
            or (category == "ended" and value["category"] == "ended")
            or (category == "once" and value["trigger"].startswith("date:"))
            or (category == "repeat" and not value["trigger"].startswith("date:"))
        )
    ]
    lifecycle_counts = {
        state: sum(schedule_lifecycle(v) == state for v in values)
        for state in ("active", "completed", "failed", "inactive")
    }
    if lifecycle:
        values = [value for value in values if schedule_lifecycle(value) == lifecycle]
    frequencies: dict[str, float] = {}

    def order(value: dict[str, Any]) -> tuple[Any, ...]:
        kind = value["category"]
        trigger = value["trigger"]
        if kind == "repeat" and trigger not in frequencies:
            frequencies[trigger] = schedule_frequency(trigger, timezone, now)
        return (
            {"once": 0, "repeat": 1, "ended": 2}[kind],
            frequencies.get(trigger, 0) if kind == "repeat" else 0,
            -(value["last_run_at"] or 0)
            if kind == "ended"
            else value["next_run_at"] or float("inf"),
            value["agent_id"],
            value["id"],
        )

    values.sort(key=order)
    end = offset + limit
    page = values[offset:end]
    for value in page:
        if "thread_title" not in value:
            value["thread_title"] = _thread_title(repos, value, user_id)
    upcoming = min(
        (value for value in values if value["next_run_at"] is not None),
        key=lambda value: value["next_run_at"],
        default=None,
    )
    return {
        "items": page,
        "next_schedule": {"next_run_at": upcoming["next_run_at"], "timezone": timezone}
        if upcoming
        else None,
        "total": len(values),
        "has_more": end < len(values),
        "next_offset": end if end < len(values) else None,
        "counts": counts,
        "lifecycle_counts": lifecycle_counts,
    }
