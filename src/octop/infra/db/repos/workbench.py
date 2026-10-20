"""Owner-scoped workbench records with compare-and-swap revisions."""

from __future__ import annotations

import json
import time
from typing import Any

from octop.infra.db.pool import DatabasePool


class WorkbenchRepo:
    def __init__(self, db: DatabasePool) -> None:
        self.db = db

    def get(self, owner: int, identity: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM workbench_records WHERE owner_user_id=? AND record_id=?",
                (owner, identity),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def list(
        self,
        owner: int,
        agent: str,
        thread: str,
        kind: str,
        *,
        resource: str | None = None,
        after: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT id,payload_json FROM workbench_records WHERE owner_user_id=? AND agent_id=? AND thread_id=? AND kind=? AND id>? "
                + ("AND resource_id=? " if resource else "")
                + "ORDER BY id LIMIT ?",
                [owner, agent, thread, kind, after, *([resource] if resource else []), limit],
            ).fetchall()
        return [{**json.loads(row["payload_json"]), "cursor": row["id"]} for row in rows]

    def save(
        self,
        owner: int,
        agent: str,
        thread: str,
        kind: str,
        identity: str,
        payload: dict[str, Any],
        *,
        expected: int = 0,
        resource: str | None = None,
    ) -> bool:
        now = time.time()
        encoded = json.dumps(payload, ensure_ascii=False)
        with self.db.transaction() as conn:
            if expected == 0:
                result = conn.execute(
                    "INSERT INTO workbench_records(record_id,kind,owner_user_id,agent_id,thread_id,resource_id,revision,payload_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(record_id) DO NOTHING",
                    (identity, kind, owner, agent, thread, resource, 1, encoded, now, now),
                )
            else:
                result = conn.execute(
                    "UPDATE workbench_records SET revision=?,payload_json=?,updated_at=? WHERE owner_user_id=? AND record_id=? AND agent_id=? AND thread_id=? AND kind=? AND revision=?",
                    (expected + 1, encoded, now, owner, identity, agent, thread, kind, expected),
                )
        return bool(result.rowcount)
