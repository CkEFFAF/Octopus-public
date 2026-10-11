from __future__ import annotations

import io
import json
import os
import sqlite3
import tarfile
from contextlib import closing
from pathlib import Path

import pytest

from octop.infra.backup import move
from octop.infra.utils.process_lock import ProcessAlreadyRunning, ProcessLock

PASSWORD = "test-only-passphrase-123"


@pytest.fixture
def home(tmp_path: Path) -> Path:
    source = tmp_path / "original"
    source.mkdir()
    (source / "config.json").write_text(
        json.dumps(
            {
                "port": 8188,
                "database": {"driver": "sqlite", "sqlite_path": str(source / "octop.db")},
            }
        )
    )
    with sqlite3.connect(source / "octop.db") as db:
        db.executescript("""
        CREATE TABLE users(id INTEGER, password_hash TEXT);
        INSERT INTO users VALUES(7,'unchanged-password-hash');
        CREATE TABLE secrets(k TEXT, v BLOB);
        INSERT INTO secrets VALUES('jwt',X'0123456789');
        CREATE TABLE agents(id INTEGER, agent_id TEXT, config_json TEXT);
        CREATE TABLE devices(device_id TEXT, token_hash TEXT, roots TEXT, permissions TEXT);
        INSERT INTO devices VALUES('keep-device-id','keep-token-hash','[]','["files_read"]');
        CREATE TABLE threads(content TEXT);
        CREATE TABLE device_operations(status TEXT);
        CREATE TABLE task_boards(payload TEXT);
        """)
        db.execute(
            "INSERT INTO agents VALUES(1,'writer',?)",
            (
                json.dumps(
                    {
                        "workspace_dir": str(source / "agents" / "writer"),
                        "welcome_message": str(source / "literal-chat-text"),
                    }
                ),
            ),
        )
        db.execute("INSERT INTO threads VALUES(?)", (str(source / "literal-chat-text"),))
    for relative, content in {
        "agents/writer/SOUL.md": "# 灵魂",
        "security/tool_guard/rules.yaml": "deny: true",
        "browser-profiles/profile/preferences": "saved-browser-profile",
        "plugins/a/skill.md": "keep-plugin",
    }.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return source


def test_encrypted_roundtrip_preserves_identity_files_and_rebases_only_config(
    home: Path, tmp_path: Path
) -> None:
    package, target = tmp_path / "manager.octopmove", tmp_path / "relocated"
    before = (home / "octop.db").read_bytes()
    report = move.create_migration_archive(home, package, PASSWORD)
    assert report["files"] >= 6
    assert b"unchanged-password-hash" not in package.read_bytes()
    assert str(home).encode() not in package.read_bytes()
    assert (home / "octop.db").read_bytes() == before
    restored = move.restore_migration_archive(package, target, PASSWORD)
    assert restored["rebased_records"] == 1
    assert not (target / ".host.lock").exists()
    assert (target / "security/tool_guard/rules.yaml").read_text() == "deny: true"
    assert (target / "browser-profiles/profile/preferences").read_text() == "saved-browser-profile"
    assert (target / "agents/writer/SOUL.md").read_text(encoding="utf-8") == "# 灵魂"
    assert json.loads((target / "config.json").read_text())["database"]["sqlite_path"] == str(
        target / "octop.db"
    )
    with sqlite3.connect(target / "octop.db") as db:
        assert db.execute("SELECT * FROM users").fetchone() == (7, "unchanged-password-hash")
        assert db.execute("SELECT * FROM secrets").fetchone() == (
            "jwt",
            bytes.fromhex("0123456789"),
        )
        assert db.execute("SELECT * FROM devices").fetchone() == (
            "keep-device-id",
            "keep-token-hash",
            "[]",
            '["files_read"]',
        )
        assert db.execute("SELECT content FROM threads").fetchone()[0] == str(
            home / "literal-chat-text"
        )
        config = json.loads(db.execute("SELECT config_json FROM agents").fetchone()[0])
        assert config["workspace_dir"] == str(target / "agents/writer")
        assert config["welcome_message"] == str(home / "literal-chat-text")


@pytest.mark.parametrize("failure", ["wrong_password", "tamper"])
def test_unauthenticated_restore_never_publishes(home: Path, tmp_path: Path, failure: str) -> None:
    package, target = tmp_path / "data.octopmove", tmp_path / "restored"
    move.create_migration_archive(home, package, PASSWORD)
    password = "another-test-password" if failure == "wrong_password" else PASSWORD
    if failure == "tamper":
        content = bytearray(package.read_bytes())
        content[-23] ^= 1
        package.write_bytes(content)
    with pytest.raises(move.MigrationError, match="Wrong migration password"):
        move.restore_migration_archive(package, target, password)
    assert not target.exists()
    assert not list(tmp_path.glob("octop-move-*"))


def test_no_overwrite_and_running_manager_refused(home: Path, tmp_path: Path) -> None:
    package = tmp_path / "data.octopmove"
    with ProcessLock(home / ".host.lock"), pytest.raises(ProcessAlreadyRunning):
        move.create_migration_archive(home, package, PASSWORD)
    assert not package.exists()
    package.write_bytes(b"existing")
    with pytest.raises(move.MigrationError, match="new output"):
        move.create_migration_archive(home, package, PASSWORD)
    assert package.read_bytes() == b"existing"
    with pytest.raises(move.MigrationError, match="already exists"):
        move.restore_migration_archive(package, home, PASSWORD)


@pytest.mark.parametrize("active", ["device", "task", "external_workspace", "postgres"])
def test_unready_source_refused(home: Path, tmp_path: Path, active: str) -> None:
    with sqlite3.connect(home / "octop.db") as db:
        if active == "device":
            db.execute("INSERT INTO device_operations VALUES('running')")
        elif active == "task":
            db.execute(
                "INSERT INTO task_boards VALUES(?)", ('{"tasks":[{"runs":[{"state":"running"}]}]}',)
            )
        elif active == "external_workspace":
            db.execute(
                "UPDATE agents SET config_json=?",
                (json.dumps({"workspace_dir": str(tmp_path / "external")}),),
            )
    if active == "postgres":
        (home / "config.json").write_text('{"database":{"driver":"postgresql"}}')
    with pytest.raises(move.MigrationError):
        move.create_migration_archive(home, tmp_path / "data.octopmove", PASSWORD)


@pytest.mark.parametrize(
    "name,kind",
    [
        ("home/../escape", tarfile.REGTYPE),
        ("home/link", tarfile.SYMTYPE),
        ("home/link", tarfile.LNKTYPE),
        ("home/NUL.txt", tarfile.REGTYPE),
        ("home/x", tarfile.FIFOTYPE),
    ],
)
def test_hostile_encrypted_archive_refused(tmp_path: Path, name: str, kind: bytes) -> None:
    archive, package = tmp_path / "unsafe.tar.gz", tmp_path / "unsafe.octopmove"
    with tarfile.open(archive, "w:gz") as tar:
        member = tarfile.TarInfo(name)
        member.type, member.linkname = kind, "../../escape"
        member.size = 1 if kind == tarfile.REGTYPE else 0
        tar.addfile(member, io.BytesIO(b"x") if member.size else None)
    move._encrypt(archive, package, PASSWORD)
    with pytest.raises(move.MigrationError):
        move.restore_migration_archive(package, tmp_path / "restored", PASSWORD)
    assert not (tmp_path / "restored").exists()
    assert not (tmp_path / "escape").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink source")
def test_export_rejects_symlink(home: Path, tmp_path: Path) -> None:
    (home / "linked").symlink_to(tmp_path)
    with pytest.raises(ValueError):
        move.create_migration_archive(home, tmp_path / "data.octopmove", PASSWORD)


def test_sqlite_wal_and_extensionless_browser_database_are_snapshotted(
    home: Path, tmp_path: Path
) -> None:
    database = home / "browser-profiles" / "profile" / "Cookies"
    with closing(sqlite3.connect(database)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE proof(value TEXT)")
        writer.execute("INSERT INTO proof VALUES('newest-committed-wal-data')")
        writer.commit()
        assert Path(str(database) + "-wal").exists()
        package = tmp_path / "wal.octopmove"
        move.create_migration_archive(home, package, PASSWORD)
    target = tmp_path / "wal-restored"
    move.restore_migration_archive(package, target, PASSWORD)
    restored = target / database.relative_to(home)
    with closing(sqlite3.connect(restored)) as db:
        assert db.execute("SELECT value FROM proof").fetchone() == ("newest-committed-wal-data",)
    assert not Path(str(restored) + "-wal").exists()


def test_database_escape_and_process_environment_are_refused(
    home: Path, tmp_path: Path, monkeypatch
) -> None:
    external = tmp_path / "other.db"
    with closing(sqlite3.connect(external)) as db:
        db.execute("CREATE TABLE other(value TEXT)")
        db.commit()
    (home / "config.json").write_text(json.dumps({"database": {"sqlite_path": "../other.db"}}))
    with pytest.raises(move.MigrationError, match="inside this home"):
        move.create_migration_archive(home, tmp_path / "escape.octopmove", PASSWORD)
    monkeypatch.setenv("OCTOP_DATABASE_URL", "postgresql://example.invalid/db")
    with pytest.raises(move.MigrationError, match="environment overrides"):
        move.create_migration_archive(home, tmp_path / "environment.octopmove", PASSWORD)


def test_restore_checks_every_file_checksum_before_publish(home: Path, tmp_path: Path) -> None:
    package, archive = tmp_path / "valid.octopmove", tmp_path / "valid.tar.gz"
    move.create_migration_archive(home, package, PASSWORD)
    move._decrypt(package, archive, PASSWORD)
    hostile_archive = tmp_path / "tampered.tar.gz"
    with (
        tarfile.open(archive, "r:gz") as source,
        tarfile.open(hostile_archive, "w:gz") as destination,
    ):
        for member in source:
            stream = source.extractfile(member)
            assert stream
            with stream:
                content = stream.read()
            if member.name == "manifest.json":
                manifest = json.loads(content)
                manifest["files"]["config.json"]["sha256"] = "0" * 64
                content = json.dumps(manifest).encode()
                member.size = len(content)
            destination.addfile(member, io.BytesIO(content))
    hostile_package = tmp_path / "tampered.octopmove"
    move._encrypt(hostile_archive, hostile_package, PASSWORD)
    target = tmp_path / "target"
    with pytest.raises(move.MigrationError, match="checksum"):
        move.restore_migration_archive(hostile_package, target, PASSWORD)
    assert not target.exists()


def test_competing_destination_is_preserved(home: Path, tmp_path: Path, monkeypatch) -> None:
    package, target = tmp_path / "valid.octopmove", tmp_path / "target"
    move.create_migration_archive(home, package, PASSWORD)
    publish = move._publish_home

    def compete(source: Path, dest: Path) -> None:
        dest.mkdir()
        publish(source, dest)

    monkeypatch.setattr(move, "_publish_home", compete)
    with pytest.raises(OSError):
        move.restore_migration_archive(package, target, PASSWORD)
    assert target.is_dir()
    assert not list(target.iterdir())


def test_export_normalizes_output_path_before_rejecting_inside_home(home: Path) -> None:
    with pytest.raises(move.MigrationError, match="outside"):
        move.create_migration_archive(home, home / "agents" / ".." / "new.octopmove", PASSWORD)
