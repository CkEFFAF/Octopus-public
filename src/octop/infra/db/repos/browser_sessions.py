"""Persistent browser login sessions (JWT sid) for server-side revocation."""

from __future__ import annotations

import time
from typing import Any

from octop.infra.db.pool import DatabasePool


class BrowserSessionRepo:
    def __init__(self, db: DatabasePool) -> None:
        self.db = db

    def create(
        self,
        *,
        sid: str,
        user_id: int,
        absolute_expires_at: float,
        auth_version_at_issue: int,
        created_at: float | None = None,
    ) -> None:
        created = float(created_at if created_at is not None else time.time())
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO browser_sessions("
                "sid, user_id, created_at, absolute_expires_at, revoked_at, auth_version_at_issue"
                ") VALUES (?, ?, ?, ?, NULL, ?)",
                (sid, user_id, created, float(absolute_expires_at), int(auth_version_at_issue)),
            )

    def get(self, sid: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM browser_sessions WHERE sid = ?", (sid,)).fetchone()
        return dict(row) if row is not None else None

    def revoke(self, sid: str) -> bool:
        now = time.time()
        with self.db.transaction() as conn:
            result = conn.execute(
                "UPDATE browser_sessions SET revoked_at = COALESCE(revoked_at, ?) WHERE sid = ?",
                (now, sid),
            )
        return bool(result.rowcount)

    def revoke_all_for_user(self, user_id: int) -> int:
        now = time.time()
        with self.db.transaction() as conn:
            result = conn.execute(
                "UPDATE browser_sessions SET revoked_at = COALESCE(revoked_at, ?) "
                "WHERE user_id = ? AND revoked_at IS NULL",
                (now, int(user_id)),
            )
        return int(result.rowcount or 0)
