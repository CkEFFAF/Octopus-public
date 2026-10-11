"""Account-owned login and enrollment keys; plaintext never reaches persistence."""

from __future__ import annotations

import time
from typing import Any

from octop.infra.db.pool import DatabasePool


class AccessKeyRepo:
    def __init__(self, db: DatabasePool) -> None:
        self.db = db

    def create(self, values: dict[str, Any]) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO account_access_keys(key_id, owner_user_id, name, secret_hash, "
                "allow_browser, allow_devices, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(
                    values[key]
                    for key in (
                        "key_id",
                        "owner_user_id",
                        "name",
                        "secret_hash",
                        "allow_browser",
                        "allow_devices",
                        "expires_at",
                        "created_at",
                    )
                ),
            )

    def get(self, key_id: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM account_access_keys WHERE key_id = ?", (key_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def find_hash(self, digest: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM account_access_keys WHERE secret_hash = ?", (digest,)
            ).fetchone()
        return dict(row) if row is not None else None

    def list_for_owner(self, owner: int) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM account_access_keys WHERE owner_user_id = ? ORDER BY created_at DESC",
                (owner,),
            ).fetchall()
        return [dict(row) for row in rows]

    def revoke(self, owner: int, key_id: str) -> bool:
        with self.db.transaction() as conn:
            result = conn.execute(
                "UPDATE account_access_keys SET revoked_at = COALESCE(revoked_at, ?) "
                "WHERE owner_user_id = ? AND key_id = ?",
                (time.time(), owner, key_id),
            )
        return bool(result.rowcount)

    def touch(self, key_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE account_access_keys SET last_used_at = ? WHERE key_id = ?",
                (time.time(), key_id),
            )
