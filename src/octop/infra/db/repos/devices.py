"""SQL persistence for account devices and their operation ledger."""

from __future__ import annotations

import json
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

from octop.infra.db.pool import DatabasePool
from octop.infra.db.repos._base import DbRow, map_rows, partial_updates


@dataclass(frozen=True)
class DeviceRow:
    pk: int
    device_id: str
    owner_user_id: int
    name: str
    platform: str
    capabilities: list[str]
    permissions: list[str]
    roots: list[dict[str, Any]]
    token_hash: str
    grant_version: int
    last_seen_at: float | None
    revoked_at: float | None
    created_at: float
    updated_at: float

    @classmethod
    def from_row(cls, row: DbRow) -> DeviceRow:
        return cls(
            pk=int(row["id"]),
            device_id=str(row["device_id"]),
            owner_user_id=int(row["owner_user_id"]),
            name=str(row["name"]),
            platform=str(row["platform"]),
            capabilities=cast(list[str], json.loads(row["capabilities"])),
            permissions=cast(list[str], json.loads(row["permissions"])),
            roots=cast(list[dict[str, Any]], json.loads(row["roots"])),
            token_hash=str(row["token_hash"]),
            grant_version=int(row["grant_version"]),
            last_seen_at=(float(row["last_seen_at"]) if row["last_seen_at"] is not None else None),
            revoked_at=(float(row["revoked_at"]) if row["revoked_at"] is not None else None),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def public(self, *, online: bool = False) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "name": self.name,
            "platform": self.platform,
            "capabilities": self.capabilities.copy(),
            "permissions": self.permissions.copy(),
            "roots": deepcopy(self.roots),
            "grant_version": self.grant_version,
            "online": online and self.revoked_at is None,
            "last_seen_at": self.last_seen_at,
            "revoked_at": self.revoked_at,
        }


@dataclass(frozen=True)
class OperationRow:
    pk: int
    operation_id: str
    device_id: str
    owner_user_id: int
    agent_id: str | None
    task_run_id: str | None
    action: str
    params: dict[str, Any]
    grant_version: int
    status: str
    result: dict[str, Any] | None
    error: str | None
    created_at: float
    updated_at: float

    @classmethod
    def from_row(cls, row: DbRow) -> OperationRow:
        return cls(
            pk=int(row["id"]),
            operation_id=str(row["operation_id"]),
            device_id=str(row["device_id"]),
            owner_user_id=int(row["owner_user_id"]),
            agent_id=(str(row["agent_id"]) if row["agent_id"] is not None else None),
            task_run_id=(str(row["task_run_id"]) if row["task_run_id"] is not None else None),
            action=str(row["action"]),
            params=cast(dict[str, Any], json.loads(row["params"])),
            grant_version=int(row["grant_version"]),
            status=str(row["status"]),
            result=(
                cast(dict[str, Any], json.loads(row["result"]))
                if row["result"] is not None
                else None
            ),
            error=(str(row["error"]) if row["error"] is not None else None),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def public(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "device_id": self.device_id,
            "owner_user_id": self.owner_user_id,
            "agent_id": self.agent_id,
            "task_run_id": self.task_run_id,
            "action": self.action,
            "params": deepcopy(self.params),
            "status": self.status,
            "result": deepcopy(self.result),
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class DeviceRepo:
    def __init__(self, db: DatabasePool) -> None:
        self._db = db

    def create(
        self,
        device_id: str,
        owner_user_id: int,
        name: str,
        platform: str,
        capabilities: list[str],
        permissions: list[str],
        roots: list[dict[str, Any]],
        token_hash: str,
    ) -> DeviceRow:
        ts = time.time()
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO devices(device_id, owner_user_id, name, platform, "
                "capabilities, permissions, roots, token_hash, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    device_id,
                    owner_user_id,
                    name,
                    platform,
                    json.dumps(capabilities),
                    json.dumps(permissions),
                    json.dumps(roots),
                    token_hash,
                    ts,
                    ts,
                ),
            )
            row = conn.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        assert row is not None
        return DeviceRow.from_row(row)

    def get(self, device_id: str) -> DeviceRow | None:
        with self._db.connect() as conn:
            row = conn.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        return DeviceRow.from_row(row) if row is not None else None

    def get_for_owner(self, device_id: str, owner_user_id: int) -> DeviceRow | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM devices WHERE device_id = ? AND owner_user_id = ?",
                (device_id, owner_user_id),
            ).fetchone()
        return DeviceRow.from_row(row) if row is not None else None

    def list_for_owner(self, owner_user_id: int) -> list[DeviceRow]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM devices WHERE owner_user_id = ? ORDER BY id DESC",
                (owner_user_id,),
            ).fetchall()
        return map_rows(rows, DeviceRow)

    def update(
        self,
        device_id: str,
        *,
        name: str | None = None,
        permissions: list[str] | None = None,
    ) -> DeviceRow | None:
        clauses, params = partial_updates(
            [
                ("name", name),
                ("permissions", json.dumps(permissions) if permissions is not None else None),
            ]
        )
        if not clauses:
            return self.get(device_id)
        if permissions is not None:
            clauses.append("grant_version = grant_version + 1")
        clauses.append("updated_at = ?")
        params.extend((time.time(), device_id))
        with self._db.transaction() as conn:
            conn.execute(
                f"UPDATE devices SET {', '.join(clauses)} "
                "WHERE device_id = ? AND revoked_at IS NULL",
                params,
            )
            row = conn.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        return DeviceRow.from_row(row) if row is not None else None

    def touch_seen(self, device_id: str) -> None:
        ts = time.time()
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE devices SET last_seen_at = ?, updated_at = ? "
                "WHERE device_id = ? AND revoked_at IS NULL",
                (ts, ts, device_id),
            )

    def revoke(self, device_id: str) -> DeviceRow | None:
        ts = time.time()
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE devices SET revoked_at = ?, updated_at = ?, "
                "grant_version = grant_version + 1 WHERE device_id = ? AND revoked_at IS NULL",
                (ts, ts, device_id),
            )
            row = conn.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        return DeviceRow.from_row(row) if row is not None else None

    def create_operation(
        self,
        operation_id: str,
        device_id: str,
        owner_user_id: int,
        action: str,
        params: dict[str, Any],
        *,
        agent_id: str | None = None,
        task_run_id: str | None = None,
        grant_version: int = 1,
        status: str = "queued",
    ) -> OperationRow:
        ts = time.time()
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO device_operations(operation_id, device_id, owner_user_id, "
                "agent_id, task_run_id, action, params, grant_version, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    operation_id,
                    device_id,
                    owner_user_id,
                    agent_id,
                    task_run_id,
                    action,
                    json.dumps(params),
                    grant_version,
                    status,
                    ts,
                    ts,
                ),
            )
            row = conn.execute(
                "SELECT * FROM device_operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
        assert row is not None
        return OperationRow.from_row(row)

    def get_operation(
        self, operation_id: str, owner_user_id: int | None = None
    ) -> OperationRow | None:
        query = "SELECT * FROM device_operations WHERE operation_id = ?"
        params: list[object] = [operation_id]
        if owner_user_id is not None:
            query += " AND owner_user_id = ?"
            params.append(owner_user_id)
        with self._db.connect() as conn:
            row = conn.execute(query, params).fetchone()
        return OperationRow.from_row(row) if row is not None else None

    def list_operations(
        self,
        owner_user_id: int,
        *,
        device_id: str | None = None,
        limit: int = 100,
    ) -> list[OperationRow]:
        query = "SELECT * FROM device_operations WHERE owner_user_id = ?"
        params: list[object] = [owner_user_id]
        if device_id is not None:
            query += " AND device_id = ?"
            params.append(device_id)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(max(0, min(limit, 100)))
        with self._db.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return map_rows(rows, OperationRow)

    def list_for_task_run(self, owner_user_id: int, task_run_id: str) -> list[OperationRow]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM device_operations WHERE owner_user_id = ? AND task_run_id = ? ORDER BY id",
                (owner_user_id, task_run_id),
            ).fetchall()
        return map_rows(rows, OperationRow)

    def update_operation(
        self,
        operation_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        expected_statuses: tuple[str, ...] | None = None,
    ) -> OperationRow | None:
        query = (
            "UPDATE device_operations SET status = ?, result = ?, error = ?, "
            "updated_at = ? WHERE operation_id = ?"
        )
        params: list[object] = [
            status,
            json.dumps(result) if result is not None else None,
            error,
            time.time(),
            operation_id,
        ]
        if expected_statuses is not None:
            if not expected_statuses:
                return self.get_operation(operation_id)
            query += f" AND status IN ({', '.join('?' for _ in expected_statuses)})"
            params.extend(expected_statuses)
        with self._db.transaction() as conn:
            conn.execute(query, params)
            row = conn.execute(
                "SELECT * FROM device_operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
        return OperationRow.from_row(row) if row is not None else None

    def recover_incomplete_operations(self) -> int:
        """Preserve evidence and confirmations without replaying uncertain work."""
        with self._db.transaction() as conn:
            result = conn.execute(
                "UPDATE device_operations SET status = 'unknown', updated_at = ? "
                "WHERE status IN ('queued', 'running')",
                (time.time(),),
            )
            return int(result.rowcount)
