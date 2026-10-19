"""Durable chat input receipts stored in the existing run event ledger."""

from __future__ import annotations

import builtins
import json
import time
from typing import Any

from octop.infra.db.pool import DatabasePool
from octop.infra.db.repos.run_events import RunEventRepo


class ChatInputRepo:
    def __init__(self, db: DatabasePool) -> None:
        self.db = db

    @staticmethod
    def event_id(owner: int, command_id: str) -> str:
        return f"chat-input:{owner}:{command_id}"

    def create(
        self,
        owner: int,
        agent_id: str,
        thread_id: str,
        command_id: str,
        *,
        kind: str,
        run_id: str,
        payload: dict[str, Any],
        status: str,
    ) -> dict[str, Any]:
        identity = self.event_id(owner, command_id)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        now = time.time()
        with self.db.transaction() as conn:
            # Serialize admission/counting for this thread on SQLite and PostgreSQL.
            conn.execute(
                "UPDATE threads SET last_active = last_active WHERE thread_id = ? AND user_id = ?",
                (thread_id, owner),
            )
            old = conn.execute(
                "SELECT * FROM run_events WHERE event_id = ?", (identity,)
            ).fetchone()
            if old is not None:
                same_payload = old["payload_json"] == encoded
                if kind == "chat_input":
                    same_payload = json.loads(old["payload_json"]).get(
                        "request_key"
                    ) == payload.get("request_key")
                if (
                    old["owner_user_id"] != owner
                    or old["agent_id"] != agent_id
                    or old["thread_id"] != thread_id
                    or old["kind"] != kind
                    or old["run_id"] != run_id
                    or not same_payload
                ):
                    raise ValueError("command_conflict")
                return RunEventRepo._public(old)
            if kind == "chat_input":
                count = conn.execute(
                    "SELECT COUNT(*) AS n FROM run_events WHERE owner_user_id = ? "
                    "AND agent_id = ? AND thread_id = ? AND kind = 'chat_input' "
                    "AND status IN ('queued', 'dispatching')",
                    (owner, agent_id, thread_id),
                ).fetchone()
                if count is not None and count["n"] >= 10:
                    raise ValueError("queue_full")
            conn.execute(
                "INSERT INTO run_events(event_id,owner_user_id,agent_id,thread_id,run_id,context_id,created_at,updated_at,kind,status,payload_json) "
                "VALUES (?,?,?,?,?,NULL,?,?,?,?,?)",
                (identity, owner, agent_id, thread_id, run_id, now, now, kind, status, encoded),
            )
            row = conn.execute(
                "SELECT * FROM run_events WHERE event_id = ?", (identity,)
            ).fetchone()
        return RunEventRepo._public(row)

    def get(self, owner: int, command_id: str) -> dict[str, Any] | None:
        return RunEventRepo(self.db).get(owner, self.event_id(owner, command_id))

    def list(self, owner: int, agent_id: str, thread_id: str) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM run_events WHERE owner_user_id = ? AND agent_id = ? AND thread_id = ? "
                "AND kind IN ('chat_input','chat_steer') ORDER BY id DESC LIMIT 100",
                (owner, agent_id, thread_id),
            ).fetchall()
            active = conn.execute(
                "SELECT * FROM run_events WHERE owner_user_id = ? AND agent_id = ? AND thread_id = ? "
                "AND kind IN ('chat_input','chat_steer') AND status IN ('queued','dispatching','requested','accepted')",
                (owner, agent_id, thread_id),
            ).fetchall()
        combined = {row["id"]: row for row in [*rows, *active]}
        return [RunEventRepo._public(combined[key]) for key in sorted(combined)]

    def transition(self, owner: int, command_id: str, previous: str, status: str) -> bool:
        with self.db.transaction() as conn:
            result = conn.execute(
                "UPDATE run_events SET status = ?, updated_at = ? WHERE owner_user_id = ? "
                "AND event_id = ? AND status = ? AND kind IN ('chat_input','chat_steer')",
                (status, time.time(), owner, self.event_id(owner, command_id), previous),
            )
        return bool(result.rowcount)

    def promote_queued_to_steer(
        self,
        owner: int,
        agent_id: str,
        thread_id: str,
        command_id: str,
        run_id: str,
        text: str,
    ) -> tuple[dict[str, Any] | None, bool]:
        """Atomically reserve a queued receipt for one direct-insertion attempt."""
        identity = self.event_id(owner, command_id)
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM run_events WHERE owner_user_id = ? AND event_id = ?",
                (owner, identity),
            ).fetchone()
            if row is None:
                return None, False
            if row["agent_id"] != agent_id or row["thread_id"] != thread_id:
                raise ValueError("command_conflict")
            payload = json.loads(row["payload_json"])
            if row["kind"] == "chat_steer" and payload.get("_promoted_from_queue"):
                if row["run_id"] != run_id:
                    raise ValueError("command_conflict")
                return RunEventRepo._public(row), False
            if row["kind"] != "chat_input" or row["status"] != "queued":
                raise ValueError("input_not_queued")

            payload["_promoted_from_queue"] = True
            payload["text"] = text
            result = conn.execute(
                "UPDATE run_events SET kind = 'chat_steer', run_id = ?, status = 'requested', "
                "payload_json = ?, updated_at = ? WHERE owner_user_id = ? AND agent_id = ? "
                "AND thread_id = ? AND event_id = ? AND kind = 'chat_input' AND status = 'queued'",
                (
                    run_id,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    time.time(),
                    owner,
                    agent_id,
                    thread_id,
                    identity,
                ),
            )
            if not result.rowcount:
                raise ValueError("input_not_queued")
            promoted = conn.execute(
                "SELECT * FROM run_events WHERE event_id = ?", (identity,)
            ).fetchone()
        return RunEventRepo._public(promoted), True

    def restore_promoted_queue(
        self, owner: int, command_id: str, run_id: str
    ) -> dict[str, Any] | None:
        """Restore a promoted item only after a definite, side-effect-free rejection."""
        identity = self.event_id(owner, command_id)
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM run_events WHERE owner_user_id = ? AND event_id = ? "
                "AND kind = 'chat_steer' AND run_id = ? AND status = 'requested'",
                (owner, identity, run_id),
            ).fetchone()
            if row is None:
                return None
            payload = json.loads(row["payload_json"])
            if not payload.pop("_promoted_from_queue", False):
                return None
            payload.pop("text", None)
            result = conn.execute(
                "UPDATE run_events SET kind = 'chat_input', run_id = ?, status = 'queued', "
                "payload_json = ?, updated_at = ? WHERE owner_user_id = ? AND event_id = ? "
                "AND kind = 'chat_steer' AND run_id = ? AND status = 'requested'",
                (
                    command_id,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    time.time(),
                    owner,
                    identity,
                    run_id,
                ),
            )
            if not result.rowcount:
                return None
            restored = conn.execute(
                "SELECT * FROM run_events WHERE event_id = ?", (identity,)
            ).fetchone()
        return RunEventRepo._public(restored)

    def ready(self, *, after_seq: int = 0) -> builtins.list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM run_events WHERE id IN (SELECT MIN(id) FROM run_events "
                "WHERE kind = 'chat_input' AND status = 'queued' GROUP BY thread_id) "
                "AND id > ? ORDER BY id LIMIT 100",
                (after_seq,),
            ).fetchall()
        return [
            {**RunEventRepo._public(row), "owner_user_id": row["owner_user_id"]} for row in rows
        ]

    def finish_run(self, owner: int, agent_id: str, thread_id: str, run_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE run_events SET status = 'unknown', updated_at = ? WHERE owner_user_id = ? "
                "AND agent_id = ? AND thread_id = ? AND run_id = ? AND kind = 'chat_steer' AND status = 'accepted'",
                (time.time(), owner, agent_id, thread_id, run_id),
            )

    def recover(self) -> None:
        # Work that may have started is never automatically replayed.
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE run_events SET status = 'unknown', updated_at = ? WHERE "
                "(kind = 'chat_input' AND status = 'dispatching') OR "
                "(kind = 'chat_steer' AND status IN ('requested','accepted'))",
                (time.time(),),
            )
