"""Durable successful report outputs, scoped to an owner and scheduled task."""

from __future__ import annotations

import time

from octop.infra.db.pool import DatabasePool


class CronReportRepo:
    def __init__(self, db: DatabasePool) -> None:
        self._db = db

    def save(
        self, *, attempt: str, owner: int, agent: str, cron: str, thread: str, output: str
    ) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO cron_report_results "
                "(attempt_id,owner_user_id,agent_id,cron_id,thread_id,output,created_at) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT(attempt_id) DO NOTHING",
                (attempt, owner, agent, cron, thread, output, time.time()),
            )

    def recent(self, *, owner: int, agent: str, cron: str, limit: int) -> list[str]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT r.output FROM cron_report_results r "
                "JOIN cron_attempts a ON a.attempt_id=r.attempt_id "
                "WHERE r.owner_user_id=? AND r.agent_id=? AND r.cron_id=? "
                "AND a.status='completed' ORDER BY r.id DESC LIMIT ?",
                (owner, agent, cron, limit),
            ).fetchall()
        return [str(row["output"]) for row in reversed(rows)]

    def allows_resource_display(self, owner: int, agent: str, source: str, display: str) -> bool:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM cron_report_results r JOIN cron_attempts a ON a.attempt_id=r.attempt_id "
                "WHERE r.owner_user_id=? AND r.agent_id=? AND a.execution_thread_id=? "
                "AND r.thread_id=? AND a.status='completed' LIMIT 1",
                (owner, agent, source, display),
            ).fetchone()
        return row is not None
