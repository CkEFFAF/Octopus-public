"""SQL persistence for account devices and their operation ledger."""

from __future__ import annotations

import json
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

from octop.infra.db.pool import DatabasePool
from octop.infra.db.repos._base import UNSET, DbRow, map_rows, optional_updates, partial_updates


def _capability_policy(row: DbRow) -> dict[str, Any] | None:
    from octop.infra.devices.capability_policy import (
        dump_capability_policy,
        parse_capability_policy,
    )

    try:
        raw = row["capability_policy_json"]
    except (KeyError, IndexError):
        return None
    if raw is None:
        return None
    policy = parse_capability_policy(raw)
    if dump_capability_policy(policy) is None:
        return None
    return policy


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
    remote_grant_mode: str
    last_seen_at: float | None
    revoked_at: float | None
    created_at: float
    updated_at: float
    trust_mode: str = "restricted"
    applied_trust_mode: str = "restricted"
    policy_revision: int = 0
    applied_policy_revision: int = 0
    working_dir: str | None = None
    runtime_metadata: dict[str, Any] | None = None
    software_version: str | None = None
    update_status: str | None = None
    capability_policy: dict[str, Any] | None = None

    @classmethod
    def from_row(cls, row: DbRow) -> DeviceRow:
        def _opt_str(key: str) -> str | None:
            try:
                value = row[key]
            except (KeyError, IndexError):
                return None
            if value is None:
                return None
            text = str(value).strip()
            return text or None

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
            remote_grant_mode=str(
                row["remote_grant_mode"] if row["remote_grant_mode"] is not None else "owner_auto"
            ),
            last_seen_at=(float(row["last_seen_at"]) if row["last_seen_at"] is not None else None),
            revoked_at=(float(row["revoked_at"]) if row["revoked_at"] is not None else None),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            trust_mode=str(row["trust_mode"]),
            applied_trust_mode=str(row["applied_trust_mode"]),
            policy_revision=int(row["policy_revision"]),
            applied_policy_revision=int(row["applied_policy_revision"]),
            working_dir=row["working_dir"],
            runtime_metadata=json.loads(row["runtime_metadata"]),
            software_version=_opt_str("software_version"),
            update_status=_opt_str("update_status"),
            capability_policy=_capability_policy(row),
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
            "remote_grant_mode": self.remote_grant_mode,
            "online": online and self.revoked_at is None,
            "last_seen_at": self.last_seen_at,
            "revoked_at": self.revoked_at,
            "trust_mode": self.trust_mode,
            "applied_trust_mode": self.applied_trust_mode,
            "policy_revision": self.policy_revision,
            "applied_policy_revision": self.applied_policy_revision,
            "working_dir": self.working_dir,
            "runtime": deepcopy(self.runtime_metadata or {}),
            "software_version": self.software_version,
            "update_status": self.update_status,
            "capability_policy": (
                deepcopy(self.capability_policy) if self.capability_policy else None
            ),
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
        roots: list[dict[str, Any]] | None = None,
        remote_grant_mode: str | None = None,
        capability_policy_json: object = UNSET,
    ) -> DeviceRow | None:
        from octop.infra.devices.capability_policy import dump_capability_policy

        policy_param: object = UNSET
        if capability_policy_json is not UNSET:
            if isinstance(capability_policy_json, dict):
                policy_param = dump_capability_policy(capability_policy_json)
            else:
                policy_param = capability_policy_json
        clauses, params = partial_updates(
            [
                ("name", name),
                ("permissions", json.dumps(permissions) if permissions is not None else None),
                ("roots", json.dumps(roots) if roots is not None else None),
                ("remote_grant_mode", remote_grant_mode),
            ]
        )
        extra_clauses, extra_params = optional_updates([("capability_policy_json", policy_param)])
        clauses.extend(extra_clauses)
        params.extend(extra_params)
        if not clauses:
            return self.get(device_id)
        if permissions is not None or roots is not None:
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

    def set_policy(
        self, device_id: str, *, trust_mode: str, permissions: list[str], working_dir: str | None
    ) -> DeviceRow:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE devices SET trust_mode = ?, permissions = ?, working_dir = ?, "
                "policy_revision = policy_revision + 1, grant_version = grant_version + 1, "
                "updated_at = ? WHERE device_id = ? AND revoked_at IS NULL",
                (trust_mode, json.dumps(permissions), working_dir, time.time(), device_id),
            )
        row = self.get(device_id)
        assert row is not None
        return row

    def report_policy(
        self, device_id: str, *, revision: int, trust_mode: str, metadata: dict[str, Any]
    ) -> DeviceRow:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE devices SET applied_policy_revision = ?, applied_trust_mode = ?, "
                "runtime_metadata = ? WHERE device_id = ? AND policy_revision = ? "
                "AND trust_mode = ? AND revoked_at IS NULL",
                (revision, trust_mode, json.dumps(metadata), device_id, revision, trust_mode),
            )
        row = self.get(device_id)
        assert row is not None
        return row

    def policy_failed(self, device_id: str, revision: int, error: str) -> None:
        row = self.get(device_id)
        if row is None or row.policy_revision != revision:
            return
        metadata = {**(row.runtime_metadata or {}), "policy_error": error[:500]}
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE devices SET runtime_metadata = ? WHERE device_id = ? AND policy_revision = ?",
                (json.dumps(metadata), device_id, revision),
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

    def list_all(self) -> list[DeviceRow]:
        with self._db.connect() as conn:
            rows = conn.execute("SELECT * FROM devices ORDER BY id DESC").fetchall()
        return map_rows(rows, DeviceRow)

    def set_update_report(
        self,
        device_id: str,
        *,
        status: str,
        software_version: str | None = None,
        error: str | None = None,
        stage_version: str | None = None,
    ) -> DeviceRow:
        row = self.get(device_id)
        if row is None:
            raise KeyError(device_id)
        metadata = dict(row.runtime_metadata or {})
        if error:
            metadata["update_error"] = error[:500]
        elif "update_error" in metadata and status in {"ok", "idle", "staged", "healthy"}:
            metadata.pop("update_error", None)
        if stage_version:
            metadata["stage_version"] = stage_version
        fields = ["update_status = ?", "runtime_metadata = ?", "updated_at = ?"]
        params: list[object] = [status, json.dumps(metadata), time.time()]
        if software_version is not None and str(software_version).strip():
            fields.append("software_version = ?")
            params.append(str(software_version).strip())
        params.append(device_id)
        with self._db.transaction() as conn:
            conn.execute(
                f"UPDATE devices SET {', '.join(fields)} WHERE device_id = ?",
                params,
            )
        out = self.get(device_id)
        assert out is not None
        return out

    def set_software_version(self, device_id: str, software_version: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE devices SET software_version = ?, updated_at = ? WHERE device_id = ?",
                (software_version, time.time(), device_id),
            )

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
