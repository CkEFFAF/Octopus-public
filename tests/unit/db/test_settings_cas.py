"""Conditional settings updates cannot overwrite newer or deleted values."""

from pathlib import Path

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.settings import SettingsRepo


def test_settings_compare_and_set(tmp_path: Path) -> None:
    pool = SqlitePool(tmp_path / "cas.db")
    run_migrations(pool)
    repo = SettingsRepo(pool)
    try:
        assert repo.compare_and_set("plugin", None, "first")
        assert not repo.compare_and_set("plugin", None, "overwrite")
        assert not repo.compare_and_set("plugin", "stale", "overwrite")
        assert repo.compare_and_set("plugin", "first", "second")
        assert repo.get("plugin") == "second"
        repo.delete("plugin")
        assert not repo.compare_and_set("plugin", "second", "resurrected")
        assert repo.get("plugin") is None
    finally:
        pool.close()
