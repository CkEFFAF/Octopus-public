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
