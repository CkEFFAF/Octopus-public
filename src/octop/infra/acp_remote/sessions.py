"""Local ACP mapping cache shared by independent adapter processes."""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def default_store_path() -> Path:
    home = Path(os.environ.get("OCTOP_HOME") or Path.home() / ".octop")
    return home / "acp-remote" / "sessions.sqlite3"


class SessionStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_store_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY, data TEXT NOT NULL)"
            )

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # Create privately before SQLite opens it. The cache never stores tokens.
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        with contextlib.suppress(OSError):
            os.chmod(self.path, 0o600)
        with contextlib.closing(sqlite3.connect(self.path, timeout=10)) as conn, conn:
            yield conn

    def get(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return dict(json.loads(row[0])) if row else None

    def put(self, session_id: str, values: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions(session_id, data) VALUES (?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET data = excluded.data",
                (session_id, json.dumps(values, ensure_ascii=False)),
            )

    def delete(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
