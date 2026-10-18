"""Immutable public snapshots; owner-scoped management and capability lookup."""

from __future__ import annotations

from typing import Any

from octop.infra.db.pool import DatabasePool


class ThreadShareRepo:
    def __init__(self, db: DatabasePool):
        self._db = db

    def create(self, value: dict[str, Any]) -> dict[str, Any]:
        columns = tuple(value)
        with self._db.transaction() as conn:
            row = conn.execute(
                f"INSERT INTO thread_shares ({','.join(columns)}) "
                f"VALUES ({','.join('?' for _ in columns)}) RETURNING *",
                tuple(value[key] for key in columns),
            ).fetchone()
            return dict(row)

    def owned(self, owner: int, share_id: str) -> dict[str, Any] | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM thread_shares WHERE owner_user_id=? AND share_id=?",
                (owner, share_id),
            ).fetchone()
        return dict(row) if row else None

    def list(
        self, owner: int, *, thread_id: str | None, before: int | None, limit: int
    ) -> list[dict[str, Any]]:
        clauses = ["owner_user_id=?"]
        params: list[object] = [owner]
        if thread_id is not None:
            clauses.append("source_thread_id=?")
            params.append(thread_id)
        if before is not None:
            clauses.append("id<?")
            params.append(before)
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM thread_shares WHERE "
                + " AND ".join(clauses)
                + " ORDER BY id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def revoke(self, owner: int, share_id: str, now: float) -> bool:
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT share_id FROM thread_shares WHERE owner_user_id=? AND share_id=?",
                (owner, share_id),
            ).fetchone()
            if row is None:
                return False
            conn.execute(
                "UPDATE thread_shares SET revoked_at=?,encrypted_token=NULL "
                "WHERE owner_user_id=? AND share_id=? AND revoked_at IS NULL",
                (now, owner, share_id),
            )
            return True

    def public(self, digest: str, now: float) -> dict[str, Any] | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT s.* FROM thread_shares s JOIN users u ON u.id=s.owner_user_id "
                "WHERE s.token_hash=? AND s.revoked_at IS NULL "
                "AND (s.expires_at IS NULL OR s.expires_at>?) AND u.disabled=0",
                (digest, now),
            ).fetchone()
        return dict(row) if row else None
