"""Persistence for audited device file transfer sessions (0044)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, cast

from octop.infra.db.pool import DatabasePool
from octop.infra.db.repos._base import UNSET, DbRow, map_rows, optional_updates


def _json_loads(raw: Any, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    if isinstance(raw, (dict, list)):
        return raw
    return json.loads(str(raw))


@dataclass(frozen=True)
class TransferRow:
    transfer_id: str
    request_id: str | None
    owner_user_id: int
    actor_user_id: int | None
    agent_id: str | None
    source_device_id: str
    source_root_id: str
    source_path: str
    source_grant_version: int
    target_device_id: str
    target_root_id: str
    target_path: str
    target_grant_version: int
    size: int | None
    sha256: str | None
    policy_version: int
    ticket_hash: str | None
    ticket_expires_at: float | None
    ticket_consumed_at: float | None
    preferred_transport: str
    actual_transport: str | None
    status: str
    bytes_done: int
    fallback_reason: str | None
    failure_direction: str | None
    error_code: str | None
    audit_id: str
    attempts: list[dict[str, Any]]
    receipts: dict[str, Any]
    operation_id: str | None
    overwrite: bool
    revoked_at: float | None
    created_at: float
    updated_at: float

    @classmethod
    def from_row(cls, row: DbRow) -> TransferRow:
        overwrite_raw = row["overwrite"]
        return cls(
            transfer_id=str(row["transfer_id"]),
            request_id=(str(row["request_id"]) if row["request_id"] is not None else None),
            owner_user_id=int(row["owner_user_id"]),
            actor_user_id=(int(row["actor_user_id"]) if row["actor_user_id"] is not None else None),
            agent_id=(str(row["agent_id"]) if row["agent_id"] is not None else None),
            source_device_id=str(row["source_device_id"]),
            source_root_id=str(row["source_root_id"]),
            source_path=str(row["source_path"]),
            source_grant_version=int(row["source_grant_version"]),
            target_device_id=str(row["target_device_id"]),
            target_root_id=str(row["target_root_id"]),
            target_path=str(row["target_path"]),
            target_grant_version=int(row["target_grant_version"]),
            size=(int(row["size"]) if row["size"] is not None else None),
            sha256=(str(row["sha256"]) if row["sha256"] is not None else None),
            policy_version=int(row["policy_version"]),
            ticket_hash=(str(row["ticket_hash"]) if row["ticket_hash"] is not None else None),
            ticket_expires_at=(
                float(row["ticket_expires_at"]) if row["ticket_expires_at"] is not None else None
            ),
            ticket_consumed_at=(
                float(row["ticket_consumed_at"]) if row["ticket_consumed_at"] is not None else None
            ),
            preferred_transport=str(row["preferred_transport"]),
            actual_transport=(
                str(row["actual_transport"]) if row["actual_transport"] is not None else None
            ),
            status=str(row["status"]),
            bytes_done=int(row["bytes_done"] or 0),
            fallback_reason=(
                str(row["fallback_reason"]) if row["fallback_reason"] is not None else None
            ),
            failure_direction=(
                str(row["failure_direction"]) if row["failure_direction"] is not None else None
            ),
            error_code=(str(row["error_code"]) if row["error_code"] is not None else None),
            audit_id=str(row["audit_id"]),
            attempts=cast(list[dict[str, Any]], _json_loads(row["attempts_json"], [])),
            receipts=cast(dict[str, Any], _json_loads(row["receipts_json"], {})),
            operation_id=(str(row["operation_id"]) if row["operation_id"] is not None else None),
            overwrite=bool(int(overwrite_raw)) if overwrite_raw is not None else False,
            revoked_at=(float(row["revoked_at"]) if row["revoked_at"] is not None else None),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def public(self, *, include_paths: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "transfer_id": self.transfer_id,
            "operation_id": self.operation_id,
            "status": self.status,
            "preferred_transport": self.preferred_transport,
            "actual_transport": self.actual_transport,
            "bytes_total": self.size,
            "bytes_done": self.bytes_done,
            "source_device_id": self.source_device_id,
            "target_device_id": self.target_device_id,
            "sha256": self.sha256,
            "fallback_reason": self.fallback_reason,
            "failure_direction": self.failure_direction,
            "error_code": self.error_code,
            "audit_id": self.audit_id,
            "attempts": list(self.attempts),
            "receipts": {
                "source": bool((self.receipts or {}).get("source")),
                "target": bool((self.receipts or {}).get("target")),
            },
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.ticket_expires_at,
            "schema_version": 1,
        }
        if include_paths:
            out["source_path"] = self.source_path
            out["target_path"] = self.target_path
            out["source_root_id"] = self.source_root_id
            out["target_root_id"] = self.target_root_id
        return out


class DeviceTransferRepo:
    def __init__(self, db: DatabasePool) -> None:
        self.db = db

    def create(self, row: dict[str, Any]) -> TransferRow:
        now = float(row.get("created_at") or time.time())
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO device_file_transfers (
                  transfer_id, request_id, owner_user_id, actor_user_id, agent_id,
                  source_device_id, source_root_id, source_path, source_grant_version,
                  target_device_id, target_root_id, target_path, target_grant_version,
                  size, sha256, policy_version, ticket_hash, ticket_expires_at,
                  ticket_consumed_at, preferred_transport, actual_transport, status,
                  bytes_done, fallback_reason, failure_direction, error_code, audit_id,
                  attempts_json, receipts_json, operation_id, overwrite, revoked_at,
                  created_at, updated_at
                ) VALUES (
                  ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                )
                """,
                (
                    row["transfer_id"],
                    row.get("request_id"),
                    int(row["owner_user_id"]),
                    row.get("actor_user_id"),
                    row.get("agent_id"),
                    row["source_device_id"],
                    row["source_root_id"],
                    row["source_path"],
                    int(row["source_grant_version"]),
                    row["target_device_id"],
                    row["target_root_id"],
                    row["target_path"],
                    int(row["target_grant_version"]),
                    row.get("size"),
                    row.get("sha256"),
                    int(row.get("policy_version") or 1),
                    row.get("ticket_hash"),
                    row.get("ticket_expires_at"),
                    row.get("ticket_consumed_at"),
                    row.get("preferred_transport") or "auto",
                    row.get("actual_transport"),
                    row["status"],
                    int(row.get("bytes_done") or 0),
                    row.get("fallback_reason"),
                    row.get("failure_direction"),
                    row.get("error_code"),
                    row["audit_id"],
                    json.dumps(row.get("attempts") or []),
                    json.dumps(row.get("receipts") or {}),
                    row.get("operation_id"),
                    1 if row.get("overwrite") else 0,
                    row.get("revoked_at"),
                    now,
                    float(row.get("updated_at") or now),
                ),
            )
        got = self.get(str(row["transfer_id"]))
        assert got is not None
        return got

    def get(self, transfer_id: str, owner: int | None = None) -> TransferRow | None:
        sql = "SELECT * FROM device_file_transfers WHERE transfer_id = ?"
        params: list[Any] = [transfer_id]
        if owner is not None:
            sql += " AND owner_user_id = ?"
            params.append(int(owner))
        with self.db.connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return TransferRow.from_row(row) if row is not None else None

    def get_by_request_id(self, owner: int, request_id: str) -> TransferRow | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM device_file_transfers WHERE owner_user_id = ? AND request_id = ?",
                (int(owner), request_id),
            ).fetchone()
        return TransferRow.from_row(row) if row is not None else None

    def get_by_operation(self, operation_id: str, owner: int | None = None) -> TransferRow | None:
        sql = "SELECT * FROM device_file_transfers WHERE operation_id = ?"
        params: list[Any] = [operation_id]
        if owner is not None:
            sql += " AND owner_user_id = ?"
            params.append(int(owner))
        with self.db.connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return TransferRow.from_row(row) if row is not None else None

    def update(
        self,
        transfer_id: str,
        *,
        status: object = UNSET,
        size: object = UNSET,
        sha256: object = UNSET,
        ticket_hash: object = UNSET,
        ticket_expires_at: object = UNSET,
        ticket_consumed_at: object = UNSET,
        preferred_transport: object = UNSET,
        actual_transport: object = UNSET,
        bytes_done: object = UNSET,
        fallback_reason: object = UNSET,
        failure_direction: object = UNSET,
        error_code: object = UNSET,
        attempts: object = UNSET,
        receipts: object = UNSET,
        operation_id: object = UNSET,
        revoked_at: object = UNSET,
        expected_statuses: tuple[str, ...] | None = None,
    ) -> TransferRow | None:
        clauses, params = optional_updates(
            [
                ("status", status),
                ("size", size),
                ("sha256", sha256),
                ("ticket_hash", ticket_hash),
                ("ticket_expires_at", ticket_expires_at),
                ("ticket_consumed_at", ticket_consumed_at),
                ("preferred_transport", preferred_transport),
                ("actual_transport", actual_transport),
                ("bytes_done", bytes_done),
                ("fallback_reason", fallback_reason),
                ("failure_direction", failure_direction),
                ("error_code", error_code),
                (
                    "attempts_json",
                    json.dumps(attempts) if attempts is not UNSET else UNSET,
                ),
                (
                    "receipts_json",
                    json.dumps(receipts) if receipts is not UNSET else UNSET,
                ),
                ("operation_id", operation_id),
                ("revoked_at", revoked_at),
            ]
        )
        if not clauses:
            return self.get(transfer_id)
        clauses.append("updated_at = ?")
        params.append(time.time())
        sql = f"UPDATE device_file_transfers SET {', '.join(clauses)} WHERE transfer_id = ?"
        params.append(transfer_id)
        if expected_statuses:
            placeholders = ", ".join("?" * len(expected_statuses))
            sql += f" AND status IN ({placeholders})"
            params.extend(expected_statuses)
        with self.db.connect() as conn:
            conn.execute(sql, params)
        return self.get(transfer_id)

    def list_for_owner(self, owner: int, *, limit: int = 50) -> list[TransferRow]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM device_file_transfers
                WHERE owner_user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (int(owner), int(limit)),
            ).fetchall()
        return map_rows(rows, TransferRow)


__all__ = ["DeviceTransferRepo", "TransferRow"]
