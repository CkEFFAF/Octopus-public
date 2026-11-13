"""SQL for independent work items and their explicit inputs (0043)."""

from __future__ import annotations

import builtins
import json
import time
from typing import Any

from octop.infra.db.pool import DatabasePool

OPEN_STATUSES = (
    "queued",
    "running",
    "waiting_input",
    "waiting_review",
    "blocked",
    "unknown",
)


class WorkItemRepo:
    def __init__(self, db: DatabasePool) -> None:
        self.db = db

    def get(self, owner: int, task_id: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM work_items WHERE owner_user_id = ? AND task_id = ?",
                (owner, task_id),
            ).fetchone()
        return self._public(row) if row is not None else None

    def get_by_command(self, owner: int, command_id: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM work_items WHERE owner_user_id = ? AND command_id = ?",
                (owner, command_id),
            ).fetchone()
        return self._public(row) if row is not None else None

    def insert(self, values: dict[str, Any]) -> dict[str, Any]:
        columns = [
            "task_id",
            "owner_user_id",
            "agent_id",
            "command_id",
            "origin_thread_id",
            "worker_thread_id",
            "title",
            "instructions",
            "status",
            "reported_outcome",
            "cancel_requested",
            "cancel_requested_at",
            "current_run_id",
            "current_attempt_id",
            "context_id",
            "target_kind",
            "device_id",
            "working_dir",
            "board_task_id",
            "block_reason",
            "needs_approval",
            "needs_credential",
            "permission_denied",
            "artifacts_json",
            "created_at",
            "updated_at",
        ]
        now = time.time()
        record = {
            "worker_thread_id": None,
            "reported_outcome": None,
            "cancel_requested": 0,
            "cancel_requested_at": None,
            "current_run_id": None,
            "current_attempt_id": None,
            "context_id": None,
            "target_kind": "device",
            "device_id": None,
            "working_dir": None,
            "board_task_id": None,
            "block_reason": None,
            "needs_approval": 0,
            "needs_credential": 0,
            "permission_denied": 0,
            "artifacts_json": "[]",
            "created_at": now,
            "updated_at": now,
            **values,
        }
        if isinstance(record.get("artifacts"), list):
            record["artifacts_json"] = json.dumps(record.pop("artifacts"), ensure_ascii=False)
        record.setdefault("instructions", "")
        with self.db.transaction() as conn:
            conn.execute(
                f"INSERT INTO work_items ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                [record[c] for c in columns],
            )
            row = conn.execute(
                "SELECT * FROM work_items WHERE task_id = ?", (record["task_id"],)
            ).fetchone()
        return self._public(row)

    def update(self, owner: int, task_id: str, **changes: Any) -> dict[str, Any] | None:
        if not changes:
            return self.get(owner, task_id)
        if "artifacts" in changes:
            changes["artifacts_json"] = json.dumps(changes.pop("artifacts"), ensure_ascii=False)
        changes["updated_at"] = time.time()
        assignments = ", ".join(f"{key} = ?" for key in changes)
        with self.db.transaction() as conn:
            conn.execute(
                f"UPDATE work_items SET {assignments} WHERE owner_user_id = ? AND task_id = ?",
                [*changes.values(), owner, task_id],
            )
            row = conn.execute(
                "SELECT * FROM work_items WHERE owner_user_id = ? AND task_id = ?",
                (owner, task_id),
            ).fetchone()
        return self._public(row) if row is not None else None

    def list(
        self,
        owner: int,
        *,
        origin_thread_id: str | None = None,
        agent_id: str | None = None,
        status_group: str = "open",
        before: float | None = None,
        limit: int = 50,
        credential_id: str | None = None,
        command_id: str | None = None,
    ) -> builtins.list[dict[str, Any]]:
        sql = (
            "SELECT * FROM work_items WHERE owner_user_id = ? "
            "AND NOT EXISTS (SELECT 1 FROM task_history_archives a "
            "WHERE a.owner_user_id=work_items.owner_user_id AND a.source='work_item' "
            "AND a.source_id=work_items.task_id AND a.source_updated_at=work_items.updated_at)"
        )
        values: list[Any] = [owner]
        if agent_id:
            sql += " AND agent_id = ?"
            values.append(agent_id)
        if credential_id is not None:
            sql += (
                " AND EXISTS (SELECT 1 FROM agent_access_object_grants g "
                "WHERE g.credential_id = ? AND g.object_kind = 'work_item' "
                "AND g.object_id = work_items.task_id)"
            )
            values.append(credential_id)
        if command_id is not None:
            sql += " AND command_id = ?"
            values.append(command_id)
        if origin_thread_id:
            sql += " AND origin_thread_id = ?"
            values.append(origin_thread_id)
        if status_group == "open":
            placeholders = ", ".join("?" for _ in OPEN_STATUSES)
            sql += f" AND (status IN ({placeholders}) OR cancel_requested = 1)"
            values.extend(OPEN_STATUSES)
        if before is not None:
            sql += " AND updated_at < ?"
            values.append(before)
        sql += " ORDER BY updated_at DESC, task_id DESC LIMIT ?"
        values.append(max(1, min(int(limit), 200)))
        with self.db.connect() as conn:
            rows = conn.execute(sql, values).fetchall()
        return [self._public(row) for row in rows]

    def list_recoverable(self) -> builtins.list[dict[str, Any]]:
        """Rows that may need post-restart observation (no auto-replay)."""
        placeholders = ", ".join("?" for _ in OPEN_STATUSES)
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM work_items WHERE status IN ({placeholders}) OR cancel_requested = 1 "
                "ORDER BY updated_at ASC",
                OPEN_STATUSES,
            ).fetchall()
        return [self._public(row) for row in rows]

    def insert_input(self, values: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        payload = values.get("payload") or {}
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        record = {
            "input_id": values["input_id"],
            "task_id": values["task_id"],
            "owner_user_id": values["owner_user_id"],
            "command_id": values["command_id"],
            "target_run_id": values.get("target_run_id"),
            "target_attempt_id": values.get("target_attempt_id"),
            "status": values.get("status", "accepted"),
            "payload_json": encoded,
            "created_at": now,
            "updated_at": now,
        }
        with self.db.transaction() as conn:
            existing = conn.execute(
                "SELECT * FROM work_item_inputs WHERE owner_user_id = ? AND command_id = ?",
                (record["owner_user_id"], record["command_id"]),
            ).fetchone()
            if existing is not None:
                if (
                    existing["task_id"] != record["task_id"]
                    or existing["payload_json"] != encoded
                    or (existing["target_run_id"] or None) != (record["target_run_id"] or None)
                    or (existing["target_attempt_id"] or None)
                    != (record["target_attempt_id"] or None)
                ):
                    raise ValueError("command_conflict")
                return self._public_input(existing)
            conn.execute(
                "INSERT INTO work_item_inputs(input_id, task_id, owner_user_id, command_id, "
                "target_run_id, target_attempt_id, status, payload_json, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    record["input_id"],
                    record["task_id"],
                    record["owner_user_id"],
                    record["command_id"],
                    record["target_run_id"],
                    record["target_attempt_id"],
                    record["status"],
                    record["payload_json"],
                    record["created_at"],
                    record["updated_at"],
                ),
            )
            row = conn.execute(
                "SELECT * FROM work_item_inputs WHERE input_id = ?", (record["input_id"],)
            ).fetchone()
        return self._public_input(row)

    def get_input_by_command(self, owner: int, command_id: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM work_item_inputs WHERE owner_user_id = ? AND command_id = ?",
                (owner, command_id),
            ).fetchone()
        return self._public_input(row) if row is not None else None

    @staticmethod
    def _public(row: Any) -> dict[str, Any]:
        artifacts = []
        try:
            artifacts = json.loads(row["artifacts_json"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            artifacts = []
        cancel = row["cancel_requested"]
        return {
            "task_id": row["task_id"],
            "owner_user_id": row["owner_user_id"],
            "agent_id": row["agent_id"],
            "command_id": row["command_id"],
            "origin_thread_id": row["origin_thread_id"],
            "worker_thread_id": row["worker_thread_id"],
            "title": row["title"],
            "instructions": row["instructions"],
            "status": row["status"],
            "reported_outcome": row["reported_outcome"],
            "cancel_requested": bool(cancel),
            "cancel_requested_at": row["cancel_requested_at"],
            "current_run_id": row["current_run_id"],
            "current_attempt_id": row["current_attempt_id"],
            "context_id": row["context_id"],
            "target_kind": row["target_kind"],
            "device_id": row["device_id"],
            "working_dir": row["working_dir"],
            "board_task_id": row["board_task_id"],
            "block_reason": row["block_reason"],
            "needs_approval": bool(row["needs_approval"]),
            "needs_credential": bool(row["needs_credential"]),
            "permission_denied": bool(row["permission_denied"]),
            "artifacts": artifacts if isinstance(artifacts, list) else [],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _public_input(row: Any) -> dict[str, Any]:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        return {
            "input_id": row["input_id"],
            "task_id": row["task_id"],
            "owner_user_id": row["owner_user_id"],
            "command_id": row["command_id"],
            "target_run_id": row["target_run_id"],
            "target_attempt_id": row["target_attempt_id"],
            "status": row["status"],
            "payload": payload if isinstance(payload, dict) else {},
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
