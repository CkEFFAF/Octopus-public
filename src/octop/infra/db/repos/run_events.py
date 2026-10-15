"""Run correlation and bounded receipt summaries; content stays in its own store."""

from __future__ import annotations

import json
import time
from typing import Any

from octop.infra.db.pool import DatabasePool


class RunEventRepo:
    def __init__(self, db: DatabasePool) -> None:
        self.db = db

    def save(
        self,
        *,
        event_id: str,
        owner: int,
        agent_id: str | None,
        thread_id: str | None,
        run_id: str,
        context_id: str | None,
        kind: str,
        status: str,
        payload: dict[str, Any],
        created_at: float | None = None,
        replace: bool = True,
    ) -> None:
        now = time.time()
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO run_events(event_id, owner_user_id, agent_id, thread_id, run_id, context_id, created_at, updated_at, kind, status, payload_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(event_id) "
                + (
                    "DO UPDATE SET updated_at = excluded.updated_at, status = excluded.status, payload_json = excluded.payload_json "
                    "WHERE run_events.owner_user_id = excluded.owner_user_id AND run_events.run_id = excluded.run_id"
                    if replace
                    else "DO NOTHING"
                ),
                (
                    event_id,
                    owner,
                    agent_id,
                    thread_id,
                    run_id,
                    context_id,
                    created_at or now,
                    now,
                    kind,
                    status,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )

    def get(self, owner: int, event_id: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM run_events WHERE owner_user_id = ? AND event_id = ?",
                (owner, event_id),
            ).fetchone()
        return self._public(row) if row is not None else None

    def due_jobs(self, before: float, *, limit: int = 64) -> list[dict[str, Any]]:
        """Recover pending observations after restart; oldest checks run first."""
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM run_events WHERE kind = 'job' "
                "AND status NOT IN ('completed', 'failed', 'cancelled') AND updated_at < ? "
                "ORDER BY updated_at, id LIMIT ?",
                (before, limit),
            ).fetchall()
        return [{**self._public(row), "owner_user_id": row["owner_user_id"]} for row in rows]

    def compare_payload(
        self,
        owner: int,
        event_id: str,
        previous: dict[str, Any],
        payload: dict[str, Any],
        status: str,
    ) -> bool:
        """Atomically advance a workflow, including across control-center workers."""
        with self.db.transaction() as conn:
            result = conn.execute(
                "UPDATE run_events SET payload_json = ?, status = ?, updated_at = ? "
                "WHERE owner_user_id = ? AND event_id = ? AND payload_json = ?",
                (
                    json.dumps(payload, ensure_ascii=False),
                    status,
                    time.time(),
                    owner,
                    event_id,
                    json.dumps(previous, ensure_ascii=False),
                ),
            )
        return bool(result.rowcount)

    def list(
        self,
        owner: int,
        agent_id: str,
        thread_id: str,
        *,
        before: int | None = None,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM run_events WHERE owner_user_id = ? AND agent_id = ? AND thread_id = ? "
                + ("AND id < ? " if before is not None else "")
                + ("AND run_id = ? " if run_id is not None else "")
                + "ORDER BY id DESC LIMIT ?",
                [
                    owner,
                    agent_id,
                    thread_id,
                    *([before] if before is not None else []),
                    *([run_id] if run_id is not None else []),
                    limit,
                ],
            ).fetchall()
        return [self._public(row) for row in rows]

    @staticmethod
    def _public(row: Any) -> dict[str, Any]:
        return {
            "seq": row["id"],
            **{
                key: row[key]
                for key in (
                    "event_id",
                    "agent_id",
                    "thread_id",
                    "run_id",
                    "context_id",
                    "kind",
                    "status",
                    "created_at",
                    "updated_at",
                )
            },
            "payload": json.loads(row["payload_json"]),
        }
