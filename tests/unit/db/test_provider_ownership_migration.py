"""Historical credentials receive one validated owner, never a guessed account."""

from pathlib import Path

import pytest

from octop.infra.db.migrate import _MIGRATIONS_DIR, run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.providers import ProviderRepo
from octop.infra.db.repos.users import UserRepo


def _legacy_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, users: int) -> SqlitePool:
    monkeypatch.delenv("PRIMARY_OWNER_USER_ID", raising=False)
    pool = SqlitePool(tmp_path / "legacy.db")
    run_migrations(pool)
    repo = UserRepo(pool)
    for index in range(users):
        repo.create(
            username=f"user{index}", password_hash="hash", role="admin" if index == 0 else "user"
        )
    with pool.connect() as conn:
        conn.executescript("""
            DROP TABLE providers;
            CREATE TABLE providers (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL, base_url TEXT, api_key TEXT, extra_json TEXT,
                models_json TEXT, note TEXT, enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
            );
            INSERT INTO providers VALUES (17, 'same', 'openai', 'https://example.test/v1', 'old-secret',
                NULL, '[{"id":"old-model"}]', 'memo', 1, 1, 2);
            INSERT INTO settings VALUES ('active_model', 'same/old-model');
            DELETE FROM settings WHERE key = 'providers.legacy_owner';
            UPDATE _schema_version SET version = 24;
        """)
    return pool


def test_single_user_migration_preserves_ids_credentials_and_active_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool = _legacy_db(tmp_path, monkeypatch, 1)
    run_migrations(pool)
    repo = ProviderRepo(pool)
    row = repo.get(1, 17)
    assert row is not None and row.api_key == "old-secret"
    assert row.models_json == '[{"id":"old-model"}]'
    with pool.connect() as conn:
        assert (
            conn.execute("SELECT value FROM settings WHERE key = 'active_model.user.1'").fetchone()[
                0
            ]
            == "same/old-model"
        )
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    run_migrations(pool)
    assert repo.get(1, 17) == row


def test_multiuser_migration_requires_valid_explicit_owner_before_any_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool = _legacy_db(tmp_path, monkeypatch, 2)
    with pytest.raises(RuntimeError, match="PRIMARY_OWNER_USER_ID"):
        run_migrations(pool)
    with pool.connect() as conn:
        assert "user_id" not in {r["name"] for r in conn.execute("PRAGMA table_info(providers)")}
        assert conn.execute("SELECT version FROM _schema_version").fetchone()[0] == 24
    monkeypatch.setenv("PRIMARY_OWNER_USER_ID", "99")
    with pytest.raises(RuntimeError, match="existing user"):
        run_migrations(pool)
    monkeypatch.setenv("PRIMARY_OWNER_USER_ID", "2")
    run_migrations(pool)
    assert ProviderRepo(pool).get(2, 17).api_key == "old-secret"
    assert ProviderRepo(pool).list_all(1) == []


def test_same_names_and_mutations_are_account_scoped(tmp_path: Path) -> None:
    pool = SqlitePool(tmp_path / "fresh.db")
    run_migrations(pool)
    users = UserRepo(pool)
    owner = users.create(username="a", password_hash="hash", role="user")
    other = users.create(username="b", password_hash="hash", role="user")
    repo = ProviderRepo(pool)
    a = repo.create(user_id=owner, name="shared-name", kind="openai", api_key="secret-a")
    b = repo.create(user_id=other, name="shared-name", kind="openai", api_key="secret-b")
    assert repo.get_by_name(owner, "shared-name").id == a
    assert repo.get_by_name(other, "shared-name").id == b
    assert repo.get(other, a) is None
    repo.update(other, a, api_key="stolen")
    repo.delete(other, a)
    assert repo.get(owner, a).api_key == "secret-a"


def test_partial_ownership_column_does_not_advance_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool = _legacy_db(tmp_path, monkeypatch, 1)
    with pool.connect() as conn:
        conn.execute("ALTER TABLE providers ADD COLUMN user_id INTEGER")
    with pytest.raises(RuntimeError, match="Incomplete providers"):
        run_migrations(pool)
    with pool.connect() as conn:
        assert conn.execute("SELECT version FROM _schema_version").fetchone()[0] == 24
        assert (
            conn.execute("SELECT api_key FROM providers WHERE id = 17").fetchone()[0]
            == "old-secret"
        )


def test_postgres_migration_has_same_account_constraints_and_no_global_name_unique() -> None:
    sql = (_MIGRATIONS_DIR / "025_provider_account_ownership.pg.sql").read_text(encoding="utf-8")
    assert "UNIQUE(user_id, name)" in sql
    assert "REFERENCES users(id)" in sql
    assert "DROP CONSTRAINT IF EXISTS providers_name_key" in sql
    assert "ALTER COLUMN user_id SET NOT NULL" in sql
