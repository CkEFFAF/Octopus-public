"""Durable collaboration projections and atomic append-only notifications."""

from __future__ import annotations

import builtins
import json
import time
from typing import Any

from octop.infra.db.pool import DatabasePool
from octop.infra.db.repos.conversation_metadata import mark_metadata_dirty, record_semantic_event


class CollaborationRepo:
    def __init__(self, db: DatabasePool) -> None:
        self.db = db

    def get(self, table: str, owner: int, identity: str) -> dict[str, Any] | None:
        assert table in {"collaboration_invocations", "collaboration_resources"}
        with self.db.connect() as conn:
            row = conn.execute(
                f"SELECT payload_json FROM {table} WHERE owner_user_id=? AND public_id=?",
                (owner, identity),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def save(
        self,
        table: str,
        owner: int,
        identity: str,
        thread: str | None,
        payload: dict[str, Any],
        event: str,
        *,
        event_id: str,
        invocation_id: str | None = None,
        resource_id: str | None = None,
        previous: dict[str, Any] | None = None,
        grants: list[dict[str, Any]] | None = None,
    ) -> bool:
        assert table in {"collaboration_invocations", "collaboration_resources"}
        encoded = json.dumps(payload, ensure_ascii=False)
        with self.db.transaction() as conn:
            # A PostgreSQL sequence is allocated before commit. Serialize one
            # root's writers before allocating IDs so replay cannot skip a late
            # commit with a smaller sequence. Other roots remain independent.
            if self.db.dialect == "postgresql" and thread:
                conn.execute(
                    "SELECT thread_id FROM threads WHERE thread_id=? FOR UPDATE", (thread,)
                ).fetchone()
            if previous is None:
                changed = conn.execute(
                    f"INSERT INTO {table}(public_id,owner_user_id,thread_id,payload_json) "
                    "VALUES (?,?,?,?) ON CONFLICT(public_id) DO NOTHING",
                    (identity, owner, thread, encoded),
                ).rowcount
            else:
                changed = conn.execute(
                    f"UPDATE {table} SET payload_json=?,thread_id=? WHERE public_id=? "
                    "AND owner_user_id=? AND payload_json=?",
                    (encoded, thread, identity, owner, json.dumps(previous, ensure_ascii=False)),
                ).rowcount
            if not changed:
                return False
            if thread:
                record_semantic_event(
                    conn,
                    thread,
                    f"collaboration:{event_id}",
                    "collaboration",
                    {
                        "event_type": event,
                        "status": payload.get("transport_status"),
                        "outcome": payload.get("task_outcome"),
                        "source_refs": [
                            {
                                "kind": "invocation"
                                if table == "collaboration_invocations"
                                else "resource",
                                "id": identity,
                            }
                        ],
                        "author_kind": "runtime",
                    },
                    float(payload.get("updated_at") or time.time()),
                )
                mark_metadata_dirty(conn, thread, "activity")
            if table == "collaboration_invocations":
                conn.execute(
                    "UPDATE collaboration_invocations SET transport_status=?,source_thread_id=?,"
                    "root_run_id=?,updated_at=?,created_at=? WHERE public_id=? AND owner_user_id=?",
                    (
                        payload["transport_status"],
                        payload["source_thread_id"],
                        payload["root_run_id"],
                        payload["updated_at"],
                        payload["created_at"],
                        identity,
                        owner,
                    ),
                )
                for resource in grants or []:
                    conn.execute(
                        "INSERT INTO collaboration_grants(owner_user_id,resource_id,version,invocation_id,"
                        "callee_agent_id,expires_at,revoked) VALUES (?,?,?,?,?,?,0) "
                        "ON CONFLICT(resource_id,invocation_id) DO NOTHING",
                        (
                            owner,
                            resource["resource_id"],
                            resource["version"],
                            identity,
                            payload["callee_agent_id"],
                            time.time() + 86400,
                        ),
                    )
                    conn.execute(
                        "INSERT INTO collaboration_events(event_id,owner_user_id,thread_id,invocation_id,"
                        "resource_id,event_type,payload_json,created_at) VALUES (?,?,?,?,?,'resource.granted','{}',?) "
                        "ON CONFLICT(event_id) DO NOTHING",
                        (
                            f"grant:{resource['resource_id']}:{identity}",
                            owner,
                            thread,
                            identity,
                            resource["resource_id"],
                            time.time(),
                        ),
                    )
            # Event payload contains references and status only; never file/message bodies.
            summary = {
                key: payload.get(key)
                for key in (
                    "transport_status",
                    "task_outcome",
                    "error_code",
                    "retryable",
                    "version",
                    "publication_state",
                    "delivery_status",
                    "cancel_requested",
                    "cancel_too_late",
                )
                if key in payload
            }
            conn.execute(
                "INSERT INTO collaboration_events(event_id,owner_user_id,thread_id,"
                "invocation_id,resource_id,event_type,payload_json,created_at) "
                "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO NOTHING",
                (
                    event_id,
                    owner,
                    thread,
                    invocation_id,
                    resource_id,
                    event,
                    json.dumps(summary),
                    time.time(),
                ),
            )
            if (
                table == "collaboration_invocations"
                and payload.get("transport_status") == "completed"
                and payload.get("cancel_too_late")
                and not (previous or {}).get("cancel_too_late")
            ):
                conn.execute(
                    "INSERT INTO collaboration_events(event_id,owner_user_id,thread_id,invocation_id,resource_id,"
                    "event_type,payload_json,created_at) VALUES (?,?,?,?,NULL,'delegation.cancel_too_late',?,?) "
                    "ON CONFLICT(event_id) DO NOTHING",
                    (
                        f"{identity}:cancel_too_late",
                        owner,
                        thread,
                        identity,
                        json.dumps({"transport_status": "completed", "cancel_too_late": True}),
                        time.time(),
                    ),
                )
        return True

    def list(self, table: str, owner: int, thread: str) -> list[dict[str, Any]]:
        assert table in {"collaboration_invocations", "collaboration_resources"}
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT payload_json FROM {table} WHERE owner_user_id=? AND thread_id=? "
                "ORDER BY id DESC LIMIT 500",
                (owner, thread),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in reversed(rows)]

    def report_resources(
        self, owner: int, agent: str, display: str
    ) -> builtins.list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT c.payload_json FROM collaboration_resources c "
                "WHERE c.owner_user_id=? AND c.thread_id IN ("
                "SELECT a.execution_thread_id FROM cron_attempts a "
                "JOIN cron_report_results r ON r.attempt_id=a.attempt_id "
                "WHERE r.owner_user_id=? AND r.agent_id=? AND r.thread_id=? AND a.status='completed') "
                "ORDER BY c.id DESC LIMIT 500",
                (owner, owner, agent, display),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in reversed(rows)]

    def references(
        self, table: str, owner: int, thread: str, identities: builtins.list[str]
    ) -> builtins.list[dict[str, Any]]:
        assert table in {"collaboration_invocations", "collaboration_resources"}
        if not identities:
            return []
        placeholders = ",".join("?" for _ in identities)
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT payload_json FROM {table} WHERE owner_user_id=? AND thread_id=? "
                f"AND public_id IN ({placeholders}) ORDER BY id",
                (owner, thread, *identities),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def events(
        self, owner: int, thread: str, after: int, limit: int
    ) -> builtins.list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM collaboration_events WHERE owner_user_id=? AND thread_id=? "
                "AND id>? ORDER BY id LIMIT ?",
                (owner, thread, after, limit),
            ).fetchall()
        return [
            {
                "seq": row["id"],
                **{
                    key: row[key]
                    for key in (
                        "event_id",
                        "event_type",
                        "invocation_id",
                        "resource_id",
                        "created_at",
                    )
                },
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    def grant(self, owner: int, resource: dict[str, Any], invocation: dict[str, Any]) -> None:
        with self.db.transaction() as conn:
            if self.db.dialect == "postgresql":
                conn.execute(
                    "SELECT thread_id FROM threads WHERE thread_id=? FOR UPDATE",
                    (invocation["scope_thread_id"],),
                ).fetchone()
            conn.execute(
                "INSERT INTO collaboration_grants(owner_user_id,resource_id,version,invocation_id,"
                "callee_agent_id,expires_at,revoked) VALUES (?,?,?,?,?,?,0) "
                "ON CONFLICT(resource_id,invocation_id) DO NOTHING",
                (
                    owner,
                    resource["resource_id"],
                    resource["version"],
                    invocation["invocation_id"],
                    invocation["callee_agent_id"],
                    time.time() + 86400,
                ),
            )
            conn.execute(
                "INSERT INTO collaboration_events(event_id,owner_user_id,thread_id,"
                "invocation_id,resource_id,event_type,payload_json,created_at) "
                "VALUES (?,?,?,?,?,'resource.granted','{}',?) ON CONFLICT(event_id) DO NOTHING",
                (
                    f"grant:{resource['resource_id']}:{invocation['invocation_id']}",
                    owner,
                    invocation["scope_thread_id"],
                    invocation["invocation_id"],
                    resource["resource_id"],
                    time.time(),
                ),
            )

    def has_grant(self, owner: int, resource: dict[str, Any], invocation: str, callee: str) -> bool:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM collaboration_grants WHERE owner_user_id=? AND resource_id=? "
                "AND version=? AND invocation_id=? AND callee_agent_id=? AND revoked=0 "
                "AND expires_at>?",
                (
                    owner,
                    resource["resource_id"],
                    resource["version"],
                    invocation,
                    callee,
                    time.time(),
                ),
            ).fetchone()
        return row is not None
