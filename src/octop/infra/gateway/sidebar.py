"""Small, user-scoped sidebar observations without loading chat history or artifacts."""

from __future__ import annotations

from typing import Any


def sidebar_status(
    *,
    gateway: Any,
    cron_manager: Any,
    agent_id: str,
    user_id: int,
    include_schedules: bool,
    background_tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    working = []
    active = set(gateway.ws_hub.active_thread_ids())
    active.update(task["thread_id"] for task in background_tasks or [] if not task["stale"])
    for thread_id in sorted(active):
        row = gateway.thread_registry.get_thread(thread_id)
        if row is None or (row.agent_id, row.user_id) != (agent_id, user_id):
            continue
        working.append(
            {
                "thread_id": row.thread_id,
                "title": row.title,
                "channel_type": row.channel_type,
                "last_active": row.last_active,
                "created_at": row.created_at,
                "pinned": row.pinned,
            }
        )
    schedules = []
    schedule_counts = {"schedules": 0, "reminders": 0}
    if include_schedules:
        for row in cron_manager.list_by_agent(
            agent_id, user_id=user_id, include_self_reminders=True
        ):
            view = cron_manager.public_view(row)
            schedule_counts["reminders" if view["self_reminder"] else "schedules"] += 1
            thread_id = view["thread_id"]
            thread = gateway.thread_registry.get_thread(thread_id) if thread_id else None
            if thread is None or (thread.agent_id, thread.user_id) != (agent_id, user_id):
                continue
            if view["scheduler_state"] == "running" and not any(
                item["thread_id"] == thread_id for item in working
            ):
                working.append(
                    {
                        "thread_id": thread.thread_id,
                        "title": thread.title,
                        "channel_type": thread.channel_type,
                        "last_active": thread.last_active,
                        "created_at": thread.created_at,
                        "pinned": thread.pinned,
                    }
                )
            schedules.append(
                {
                    "thread_id": thread_id,
                    "id": view["id"],
                    "name": view["name"],
                    "enabled": view["enabled"],
                    "scheduler_state": view["scheduler_state"],
                    "next_run_at": view["next_run_at"],
                    "timezone": view["timezone"],
                    "last_run_at": view["last_run_at"],
                    "created_at": row.created_at,
                    "self_reminder": view["self_reminder"],
                }
            )
    return {
        "working_threads": working,
        "schedules": schedules,
        "schedule_counts": schedule_counts,
        "background_tasks": background_tasks or [],
    }
