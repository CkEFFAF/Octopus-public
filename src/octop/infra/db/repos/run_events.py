"""Run correlation and bounded receipt summaries; content stays in its own store."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Sequence
from typing import Any

from octop.infra.db.pool import DatabasePool
from octop.infra.db.repos.conversation_metadata import (
    encoded,
    mark_metadata_dirty,
    record_semantic_event,
)


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
            previous = conn.execute(
                "SELECT status,payload_json FROM run_events WHERE event_id=? AND owner_user_id=?",
                (event_id, owner),
            ).fetchone()
            saved = conn.execute(
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
            ).rowcount
            if saved:
                self._metadata_event(
                    conn, thread_id, event_id, kind, status, payload, previous, now
                )

    @staticmethod
    def _metadata_event(
        conn: Any,
        thread: str | None,
        event_id: str,
        kind: str,
        status: str,
        payload: dict[str, Any],
        previous: Any,
        now: float,
    ) -> None:
        if not thread or kind not in {"tool", "job", "dispatch", "device", "workflow"}:
            return
        # Receipt transitions, not poll timestamps or stdout, affect semantic progress.
        facts = {
            key: payload[key]
            for key in (
                "name",
                "action",
                "job_id",
                "task_outcome",
                "error_code",
                "task_id",
                "invocation_id",
            )
            if key in payload and isinstance(payload[key], (str, int, bool))
        }
        receipt = payload.get("receipt")
        receipt = receipt if isinstance(receipt, dict) else {}
        facts.update({key: receipt[key] for key in ("returncode", "status") if key in receipt})
        old_payload = json.loads(previous["payload_json"]) if previous else {}
        if kind == "workflow":
            facts["version"] = payload.get("version", 0)
        old_receipt = old_payload.get("receipt")
        old_receipt = old_receipt if isinstance(old_receipt, dict) else {}
        if (
            previous
            and previous["status"] == status
            and all(
                old_payload.get(key) == payload.get(key)
                for key in facts
                if key not in {"returncode", "status"}
            )
            and all(old_receipt.get(key) == receipt.get(key) for key in ("returncode", "status"))
        ):
            return
        key = hashlib.sha256(encoded([status, facts]).encode()).hexdigest()[:20]
        record_semantic_event(
            conn,
            thread,
            f"run:{event_id}:{key}",
            "execution",
            {
                "status": status,
                "facts": facts,
                "source_refs": [{"kind": "run", "id": event_id}],
                "author_kind": "runtime",
            },
            now,
        )
        mark_metadata_dirty(conn, thread, "activity")

    def get(self, owner: int, event_id: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM run_events WHERE owner_user_id = ? AND event_id = ?",
                (owner, event_id),
            ).fetchone()
        return self._public(row) if row is not None else None

    def active(self, owner: int, agent: str, thread: str, limit: int = 200) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM run_events WHERE owner_user_id=? AND agent_id=? AND thread_id=? AND kind IN ('dispatch','job','tool','device') AND status IN ('running','started','accepted','waiting') ORDER BY updated_at DESC,id DESC LIMIT ?",
                (owner, agent, thread, limit),
            ).fetchall()
        return [self._public(row) for row in rows]

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
            original = conn.execute(
                "SELECT thread_id,kind,status,payload_json FROM run_events WHERE owner_user_id=? AND event_id=?",
                (owner, event_id),
            ).fetchone()
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
            if result.rowcount and original:
                self._metadata_event(
                    conn,
                    original["thread_id"],
                    event_id,
                    original["kind"],
                    status,
                    payload,
                    original,
                    time.time(),
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
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM run_events WHERE owner_user_id = ? AND agent_id = ? AND thread_id = ? "
                + ("AND id < ? " if before is not None else "")
                + ("AND run_id = ? " if run_id is not None else "")
                + ("AND kind = ? " if kind is not None else "")
                + "ORDER BY id DESC LIMIT ?",
                [
                    owner,
                    agent_id,
                    thread_id,
                    *([before] if before is not None else []),
                    *([run_id] if run_id is not None else []),
                    *([kind] if kind is not None else []),
                    limit,
                ],
            ).fetchall()
        return [self._public(row) for row in rows]

    def get_many(self, owner: int, identities: Sequence[str]) -> dict[str, dict[str, Any]]:
        if not identities:
            return {}
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM run_events WHERE owner_user_id=? AND event_id IN ("
                + ",".join("?" for _ in identities)
                + ")",
                [owner, *identities],
            ).fetchall()
        return {row["event_id"]: self._public(row) for row in rows}

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
