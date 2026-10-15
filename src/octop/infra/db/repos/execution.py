"""Immutable execution targets stored separately from expert content storage."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

from octop.infra.db.pool import DatabasePool
from octop.infra.utils.ulid import new_ulid


@dataclass(frozen=True)
class ExecutionContext:
    context_id: str
    owner_user_id: int
    device_id: str | None
    working_dir: str | None
    policy_revision: int
    grant_version: int
    work_mode: str
    source: str
    target_kind: str = "device"
    agent_id: str | None = None
    thread_id: str | None = None
    run_id: str | None = None
    created_at: float = 0

    def public(self) -> dict[str, Any]:
        return asdict(self)


class ExecutionContextRepo:
    def __init__(self, db: DatabasePool) -> None:
        self.db = db

    def create(self, **values: Any) -> ExecutionContext:
        context = ExecutionContext(context_id=new_ulid(), created_at=time.time(), **values)
        record = context.public()
        columns = list(record)
        with self.db.transaction() as conn:
            conn.execute(
                f"INSERT INTO execution_contexts ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                [record[key] for key in columns],
            )
        return context

    def get(self, owner: int, context_id: str) -> ExecutionContext | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM execution_contexts WHERE context_id = ? AND owner_user_id = ?",
                (context_id, owner),
            ).fetchone()
        if row is None:
            return None
        return ExecutionContext(**{key: row[key] for key in ExecutionContext.__dataclass_fields__})

    def selection(self, owner: int, thread_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT device_id, working_dir, work_mode, target_kind FROM thread_execution_settings WHERE owner_user_id = ? AND thread_id = ?",
                (owner, thread_id),
            ).fetchone()
        return (
            dict(row)
            if row is not None
            else {
                "device_id": None,
                "working_dir": None,
                "work_mode": "agentic",
                "target_kind": "device",
            }
        )

    def save_selection(self, owner: int, thread_id: str, values: dict[str, Any]) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO thread_execution_settings(thread_id, owner_user_id, device_id, working_dir, work_mode, target_kind) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(thread_id) DO UPDATE SET "
                "device_id = excluded.device_id, working_dir = excluded.working_dir, work_mode = excluded.work_mode, target_kind = excluded.target_kind",
                (
                    thread_id,
                    owner,
                    values.get("device_id") or None,
                    values.get("working_dir"),
                    values["work_mode"],
                    values.get("target_kind", "device"),
                ),
            )
