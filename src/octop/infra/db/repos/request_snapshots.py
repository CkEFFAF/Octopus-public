"""Durable provider request snapshots, independent of live harness instances."""

from __future__ import annotations

import json
from typing import Any

from octop.infra.db.pool import DatabasePool


class RequestSnapshotRepo:
    def __init__(self, db: DatabasePool) -> None:
        self.db = db

    def save(self, owner: int, agent_id: str, thread_id: str, snapshot: dict[str, Any]) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO request_snapshots(request_id, owner_user_id, agent_id, thread_id, created_at, payload_json) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(request_id) DO UPDATE SET payload_json = excluded.payload_json "
                "WHERE request_snapshots.owner_user_id = excluded.owner_user_id "
                "AND request_snapshots.agent_id = excluded.agent_id AND request_snapshots.thread_id = excluded.thread_id",
                (
                    snapshot["request_id"],
                    owner,
                    agent_id,
                    thread_id,
                    snapshot["created_at"],
                    json.dumps(snapshot, ensure_ascii=False),
                ),
            )

    def list(
        self,
        owner: int,
        agent_id: str,
        thread_id: str,
        *,
        before: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT id, payload_json FROM request_snapshots WHERE owner_user_id = ? AND agent_id = ? AND thread_id = ? "
                + ("AND id < ? " if before is not None else "")
                + "ORDER BY id DESC LIMIT ?",
                [owner, agent_id, thread_id, *([before] if before is not None else []), limit],
            ).fetchall()
        return [{**json.loads(row["payload_json"]), "seq": row["id"]} for row in rows]

    def get(
        self, owner: int, agent_id: str, thread_id: str, request_id: str
    ) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id, payload_json FROM request_snapshots WHERE owner_user_id = ? AND agent_id = ? AND thread_id = ? AND request_id = ?",
                (owner, agent_id, thread_id, request_id),
            ).fetchone()
        return {**json.loads(row["payload_json"]), "seq": row["id"]} if row else None
