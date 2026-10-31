"""Durable scheduled delivery attempts, independent of mutable session bindings."""

from __future__ import annotations

import time
from typing import Any

from octop.infra.db.pool import DatabasePool


class CronAttemptRepo:
    def __init__(self, db: DatabasePool) -> None:
        self.db = db

    def create(
        self, attempt: str, owner: int, agent: str, cron: str, thread: str | None, reason: str
    ) -> None:
        now = time.time()
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO cron_attempts(attempt_id,owner_user_id,agent_id,cron_id,source_thread_id,reason,status,revision,created_at,updated_at) VALUES (?,?,?,?,?,?,'waiting_session',1,?,?)",
                (attempt, owner, agent, cron, thread, reason, now, now),
            )

    def update(
        self,
        owner: int,
        attempt: str,
        status: str,
        *,
        thread: str | None = None,
        run: str | None = None,
        error: str | None = None,
        result: str | None = None,
    ) -> None:
        now = time.time()
        terminal = status in {"delivered", "completed", "failed", "cancelled", "unknown"}
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE cron_attempts SET status=?,revision=revision+1,updated_at=?,actual_thread_id=COALESCE(?,actual_thread_id),run_id=COALESCE(?,run_id),started_at=COALESCE(started_at,?),finished_at=?,public_error=?,result_excerpt=? WHERE owner_user_id=? AND attempt_id=? AND status IN ('waiting_session','running') AND (run_id IS NULL OR ? IS NULL OR run_id=?)",
                (
                    status,
                    now,
                    thread,
                    run,
                    now if status == "running" else None,
                    now if terminal else None,
                    error,
                    result,
                    owner,
                    attempt,
                    run,
                    run,
                ),
            )

    def recover(self) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE cron_attempts SET status='unknown',revision=revision+1,updated_at=?,finished_at=?,public_error='Process restarted before delivery outcome was confirmed' WHERE status IN ('waiting_session','running')",
                (time.time(), time.time()),
            )

    def bind_report_execution(self, owner: int, attempt: str, thread: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE cron_attempts SET execution_thread_id=?,checkpoint_cleanup='pending' "
                "WHERE owner_user_id=? AND attempt_id=? AND status='running'",
                (thread, owner, attempt),
            )

    def report_cleanup_candidates(self, owner: int, agent: str, cron: str) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT attempt_id,execution_thread_id FROM cron_attempts "
                "WHERE owner_user_id=? AND agent_id=? AND cron_id=? "
                "AND checkpoint_cleanup='pending' AND status IN ('completed','failed','cancelled','unknown') "
                "ORDER BY id LIMIT 10",
                (owner, agent, cron),
            ).fetchall()
        return [dict(row) for row in rows]

    def report_cleanup_done(self, owner: int, attempt: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE cron_attempts SET checkpoint_cleanup='done' WHERE owner_user_id=? AND attempt_id=?",
                (owner, attempt),
            )

    def report_cleanup_scopes(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT owner_user_id,agent_id,cron_id FROM cron_attempts "
                "WHERE checkpoint_cleanup='pending' AND status IN ('completed','failed','cancelled','unknown') "
                "ORDER BY owner_user_id,agent_id,cron_id LIMIT 100"
            ).fetchall()
        return [dict(row) for row in rows]

    def listing(
        self, owner: int, agent: str, cron: str, before: int | None = None, limit: int = 50
    ) -> dict[str, Any]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM cron_attempts WHERE owner_user_id=? AND agent_id=? AND cron_id=? "
                + ("AND id<? " if before is not None else "")
                + "ORDER BY id DESC LIMIT ?",
                [owner, agent, cron, *([before] if before is not None else []), limit + 1],
            ).fetchall()
        items = [dict(row) for row in rows[:limit]]
        return {
            "items": items,
            "has_more": len(rows) > limit,
            "next_cursor": items[-1]["id"] if len(rows) > limit else None,
        }
