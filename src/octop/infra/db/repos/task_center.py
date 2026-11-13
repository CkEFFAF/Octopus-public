"""Read existing task sources under the requesting account's identity."""

from __future__ import annotations

from typing import Any

from octop.infra.db.pool import DatabasePool


class TaskCenterRepo:
    def __init__(self, db: DatabasePool) -> None:
        self.db = db

    def records(
        self, owner: int, agent: str = "", thread: str = "", *, archived: bool = False
    ) -> dict[str, list[dict[str, Any]]]:
        sources = {
            "work_item": (
                "work_items",
                "r.task_id AS source_id,r.title,r.status,r.updated_at,r.cancel_requested,"
                "r.origin_thread_id AS thread_id",
                "origin_thread_id",
                "",
            ),
            "receipt": (
                "run_events",
                "r.event_id AS source_id,r.kind,r.status,r.updated_at,r.run_id,"
                "r.payload_json,r.thread_id",
                "thread_id",
                " AND r.kind IN ('job','dispatch')",
            ),
            "plan": (
                "workbench_records",
                "r.record_id AS source_id,r.updated_at,r.payload_json,r.thread_id",
                "thread_id",
                " AND r.kind='plan'",
            ),
        }
        result: dict[str, list[dict[str, Any]]] = {}
        with self.db.connect() as conn:
            for source, (table, columns, thread_column, extra) in sources.items():
                sql = (
                    f"SELECT {columns},r.agent_id,a.name AS agent_name,t.title AS thread_title "
                    f"FROM {table} r LEFT JOIN agents a ON a.agent_id=r.agent_id "
                    f"LEFT JOIN threads t ON t.thread_id=r.{thread_column} "
                    "AND t.user_id=r.owner_user_id AND t.agent_id=r.agent_id "
                    "WHERE r.owner_user_id=?"
                )
                values: list[Any] = [owner]
                identity = {"work_item": "task_id", "receipt": "event_id", "plan": "record_id"}[
                    source
                ]
                sql += (
                    " AND "
                    + ("" if archived else "NOT ")
                    + "EXISTS (SELECT 1 FROM task_history_archives x WHERE "
                    "x.owner_user_id=r.owner_user_id AND x.source=? "
                    f"AND x.source_id=r.{identity} AND x.source_updated_at=r.updated_at)"
                )
                values.append(source)
                if agent:
                    sql += " AND r.agent_id=?"
                    values.append(agent)
                if thread:
                    sql += f" AND r.{thread_column}=?"
                    values.append(thread)
                rows = conn.execute(sql + extra + " ORDER BY r.updated_at DESC", values).fetchall()
                result[source] = [dict(row) for row in rows]
        return result

    def threads(self, owner: int, agent: str = "") -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT thread_id,title,agent_id FROM threads WHERE user_id=? "
                + ("AND agent_id=? " if agent else "")
                + "ORDER BY last_active DESC",
                [owner, *([agent] if agent else [])],
            ).fetchall()
        return [dict(row) for row in rows]
