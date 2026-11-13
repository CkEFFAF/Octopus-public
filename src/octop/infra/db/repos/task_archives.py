"""Logical task history archives. Original execution evidence is retained."""

from __future__ import annotations

import json
import time

from octop.infra.db.pool import DatabasePool

COMPLETED_RETENTION_SECONDS = 7 * 86400
FAILED_RETENTION_SECONDS = 30 * 86400


class TaskArchiveRepo:
    def __init__(self, db: DatabasePool) -> None:
        self.db = db

    def archive_terminal(self, now: float | None = None) -> None:
        stamp = time.time() if now is None else now
        for table, source, identity, extra in (
            ("work_items", "work_item", "task_id", ""),
            ("run_events", "receipt", "event_id", " AND kind IN ('job','dispatch')"),
        ):
            with self.db.transaction() as conn:
                conn.execute(
                    "INSERT INTO task_history_archives"
                    "(owner_user_id,source,source_id,source_updated_at,archived_at) "
                    f"SELECT owner_user_id,?,{identity},updated_at,? FROM {table} "
                    "WHERE ((status IN ('completed','cancelled','succeeded') AND updated_at<?) "
                    "OR (status='failed' AND updated_at<?))"
                    + extra
                    + " ON CONFLICT(owner_user_id,source,source_id) DO UPDATE SET "
                    "source_updated_at=excluded.source_updated_at,archived_at=excluded.archived_at "
                    "WHERE task_history_archives.source_updated_at<>excluded.source_updated_at",
                    (
                        source,
                        stamp,
                        stamp - COMPLETED_RETENTION_SECONDS,
                        stamp - FAILED_RETENTION_SECONDS,
                    ),
                )
        # Plans have JSON task states. Only old, fully terminal declarations qualify.
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT owner_user_id,record_id,updated_at,payload_json FROM workbench_records r "
                "WHERE kind='plan' AND updated_at<? AND NOT EXISTS "
                "(SELECT 1 FROM task_history_archives a WHERE a.owner_user_id=r.owner_user_id "
                "AND a.source='plan' AND a.source_id=r.record_id AND a.source_updated_at=r.updated_at)",
                (stamp - COMPLETED_RETENTION_SECONDS,),
            ).fetchall()
        for row in rows:
            tasks = json.loads(row["payload_json"]).get("tasks", [])
            if (
                any(t.get("status") == "failed" for t in tasks)
                and row["updated_at"] >= stamp - FAILED_RETENTION_SECONDS
            ):
                continue
            if tasks and all(
                t.get("status") in {"completed", "cancelled", "failed"} for t in tasks
            ):
                self.mark(row["owner_user_id"], "plan", row["record_id"], row["updated_at"], stamp)

    def mark(
        self, owner: int, source: str, identity: str, updated_at: float, now: float | None = None
    ) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO task_history_archives"
                "(owner_user_id,source,source_id,source_updated_at,archived_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(owner_user_id,source,source_id) DO UPDATE SET "
                "source_updated_at=excluded.source_updated_at,archived_at=excluded.archived_at",
                (owner, source, identity, updated_at, time.time() if now is None else now),
            )

    def archived(self, owner: int, source: str, identity: str, updated_at: float) -> bool:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM task_history_archives WHERE owner_user_id=? AND source=? "
                "AND source_id=? AND source_updated_at=?",
                (owner, source, identity, updated_at),
            ).fetchone()
        return row is not None
