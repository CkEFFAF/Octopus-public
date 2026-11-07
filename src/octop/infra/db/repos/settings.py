"""Settings KV store — lightweight key/value pairs backed by SQLite."""

from __future__ import annotations

from octop.infra.db.pool import DatabasePool


class SettingsRepo:
    _KEY_ACTIVE_MODEL = "active_model"

    def __init__(self, db: DatabasePool):
        self._db = db

    def get(self, key: str) -> str | None:
        with self._db.connect() as conn:
            r = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return r["value"] if r else None

    def set(self, key: str, value: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def delete(self, key: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))

    def compare_and_set(self, key: str, expected: str | None, value: str) -> bool:
        """Atomically replace a previously read value, or create an absent key."""
        with self._db.transaction() as conn:
            if expected is None:
                result = conn.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO NOTHING",
                    (key, value),
                )
            else:
                result = conn.execute(
                    "UPDATE settings SET value = ? WHERE key = ? AND value = ?",
                    (value, key, expected),
                )
            return bool(result.rowcount == 1)

    def get_active_model(self, user_id: int) -> tuple[str, str]:
        """Return (provider_name, model_id); empty strings if not set."""
        raw = self.get(f"{self._KEY_ACTIVE_MODEL}.user.{user_id}") or ""
        name, _, model = raw.partition("/")
        return name, model

    def set_active_model(self, user_id: int, provider_name: str, model_id: str) -> None:
        self.set(f"{self._KEY_ACTIVE_MODEL}.user.{user_id}", f"{provider_name}/{model_id}")
