"""Small, user-scoped sidebar observations without loading chat history or artifacts."""

from __future__ import annotations

from typing import Any


def sidebar_status(
    *, gateway: Any, cron_manager: Any, agent_id: str, user_id: int, include_schedules: bool
) -> dict[str, Any]:
    working = []
    for thread_id in sorted(gateway.ws_hub.active_thread_ids()):
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
    if include_schedules:
        for row in cron_manager.list_by_agent(
            agent_id, user_id=user_id, include_self_reminders=True
        ):
            view = cron_manager.public_view(row)
            thread_id = view["thread_id"]
            thread = gateway.thread_registry.get_thread(thread_id) if thread_id else None
            if thread is None or (thread.agent_id, thread.user_id) != (agent_id, user_id):
                continue
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
    return {"working_threads": working, "schedules": schedules}
