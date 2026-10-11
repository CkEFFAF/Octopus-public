"""Device identity, account boundaries, and durable operation recovery."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from octop.config import OctopConfig
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.devices import DeviceRepo, DeviceRow
from octop.infra.db.repos.users import UserRepo
from octop.infra.db.services import RepoBundle, SharedServices
from octop.infra.utils.paths import PathLayout


@pytest.fixture
def db(tmp_path: Path) -> Iterator[SqlitePool]:
    pool = SqlitePool(tmp_path / "devices.db")
    run_migrations(pool)
    yield pool
    pool.close()


@pytest.fixture
def repo(db: SqlitePool) -> DeviceRepo:
    return DeviceRepo(db)


@pytest.fixture
def owners(db: SqlitePool) -> tuple[int, int]:
    users = UserRepo(db)
    return (
        users.create(username="alice", password_hash="test-hash", role="user"),
        users.create(username="bob", password_hash="test-hash", role="user"),
    )


def create_device(repo: DeviceRepo, owner: int, device_id: str = "device-a") -> DeviceRow:
    return repo.create(
        device_id,
        owner,
        "工作站",
        "windows",
        ["desktop_view", "desktop_control", "files_read", "files_write"],
        ["desktop_view", "files_read"],
        [{"id": "docs", "name": "文件", "path": "C:\\Shared", "read": True, "write": False}],
        f"test-token-hash-{device_id}",
    )


def test_devices_are_distinct_and_account_scoped(repo: DeviceRepo, owners: tuple[int, int]) -> None:
    alice, bob = owners
    first = create_device(repo, alice)
    second = create_device(repo, alice, "device-b")
    create_device(repo, bob, "device-c")
    assert first.device_id != second.device_id
    assert first.name == second.name
    assert repo.get_for_owner(first.device_id, alice) == first
    assert repo.get_for_owner(first.device_id, bob) is None
    assert repo.get("absent") is None
    assert {row.device_id for row in repo.list_for_owner(alice)} == {"device-a", "device-b"}
    assert [row.device_id for row in repo.list_for_owner(bob)] == ["device-c"]


def test_public_device_hides_authentication_and_copies_grants(
    repo: DeviceRepo, owners: tuple[int, int]
) -> None:
    row = create_device(repo, owners[0])
    public = row.public(online=True)
    assert set(public) == {
        "device_id",
        "name",
        "platform",
        "capabilities",
        "permissions",
        "roots",
        "grant_version",
        "online",
        "last_seen_at",
        "revoked_at",
    }
    assert public["online"] is True
    assert public["roots"][0]["path"] == "C:\\Shared"
    public["roots"][0]["write"] = True
    public["permissions"].append("command_exec")
    assert row.roots[0]["write"] is False
    assert "command_exec" not in row.permissions


def test_device_ids_and_credentials_are_unique(repo: DeviceRepo, owners: tuple[int, int]) -> None:
    first = create_device(repo, owners[0])
    with pytest.raises(sqlite3.IntegrityError):
        create_device(repo, owners[1])
    with pytest.raises(sqlite3.IntegrityError):
        repo.create("other", owners[1], "Other", "linux", [], [], [], first.token_hash)
    assert len(repo.list_for_owner(owners[1])) == 0


def test_grant_change_increments_version_but_rename_does_not(
    repo: DeviceRepo, owners: tuple[int, int]
) -> None:
    row = create_device(repo, owners[0])
    renamed = repo.update(row.device_id, name="Linux workstation")
    assert renamed is not None
    assert renamed.grant_version == 1
    assert renamed.name == "Linux workstation"
    denied = repo.update(row.device_id, permissions=[])
    assert denied is not None
    assert denied.permissions == []
    assert denied.grant_version == 2
    assert repo.update(row.device_id) == denied
    assert repo.update("absent", name="Missing") is None


def test_seen_and_idempotent_revocation_are_durable(
    repo: DeviceRepo, db: SqlitePool, owners: tuple[int, int]
) -> None:
    row = create_device(repo, owners[0])
    repo.touch_seen(row.device_id)
    seen = repo.get(row.device_id)
    assert seen is not None and seen.last_seen_at is not None
    revoked = repo.revoke(row.device_id)
    assert revoked is not None and revoked.revoked_at is not None
    assert revoked.grant_version == 2
    assert revoked.public(online=True)["online"] is False
    repo.touch_seen(row.device_id)
    assert repo.update(row.device_id, name="Changed", permissions=["command_exec"]) == revoked
    assert repo.revoke(row.device_id) == revoked
    assert DeviceRepo(db).get(row.device_id) == revoked
    assert repo.list_for_owner(owners[0]) == [revoked]
    assert repo.revoke("absent") is None


def test_operation_records_public_fields_and_owner_boundary(
    repo: DeviceRepo, owners: tuple[int, int]
) -> None:
    alice, bob = owners
    row = create_device(repo, alice)
    params: dict[str, Any] = {"root_id": "docs", "path": "notes.txt"}
    operation = repo.create_operation(
        "op-a",
        row.device_id,
        alice,
        "files.stat",
        params,
        agent_id="agent-a",
        grant_version=row.grant_version,
    )
    assert operation.params == params
    assert operation.agent_id == "agent-a"
    assert repo.get_operation("op-a", alice) == operation
    assert repo.get_operation("op-a", bob) is None
    assert repo.get_operation("absent", alice) is None
    assert "grant_version" not in operation.public()
    assert "pk" not in operation.public()
    assert operation.public()["owner_user_id"] == alice
    with pytest.raises(sqlite3.IntegrityError):
        repo.create_operation("op-cross-owner", row.device_id, bob, "ping", {})
    assert repo.list_operations(bob) == []


def test_operations_list_filters_device_and_has_recent_limit(
    repo: DeviceRepo, owners: tuple[int, int]
) -> None:
    alice, bob = owners
    create_device(repo, alice)
    create_device(repo, alice, "device-b")
    create_device(repo, bob, "device-c")
    for index in range(105):
        repo.create_operation(f"op-{index:03d}", "device-a", alice, "ping", {})
    repo.create_operation("op-b", "device-b", alice, "status", {})
    repo.create_operation("op-c", "device-c", bob, "status", {})
    recent = repo.list_operations(alice)
    assert len(recent) == 100
    assert recent[0].operation_id == "op-b"
    assert [row.operation_id for row in repo.list_operations(alice, device_id="device-b")] == [
        "op-b"
    ]
    assert len(repo.list_operations(alice, device_id="device-a", limit=500)) == 100
    assert repo.list_operations(alice, device_id="device-c") == []
    assert repo.list_operations(alice, limit=0) == []


def test_operation_result_and_error_are_persisted(
    repo: DeviceRepo, db: SqlitePool, owners: tuple[int, int]
) -> None:
    create_device(repo, owners[0])
    repo.create_operation("op-result", "device-a", owners[0], "files.stat", {})
    result = {"size": 8, "sha256": "sample-digest", "nested": {"ok": True}}
    completed = repo.update_operation("op-result", status="completed", result=result)
    assert completed is not None
    assert completed.result == result
    assert DeviceRepo(db).get_operation("op-result") == completed
    completed.public()["result"]["nested"]["ok"] = False
    assert completed.result["nested"]["ok"] is True
    failed = repo.update_operation("op-result", status="failed", error="permission_denied")
    assert failed is not None
    assert failed.result is None
    assert failed.error == "permission_denied"
    assert repo.update_operation("absent", status="failed") is None


def test_restart_recovers_only_incomplete_operations_without_replay(
    repo: DeviceRepo, db: SqlitePool, owners: tuple[int, int]
) -> None:
    create_device(repo, owners[0])
    statuses = [
        "pending_confirmation",
        "queued",
        "running",
        "completed",
        "failed",
        "cancelled",
        "unknown",
    ]
    for status in statuses:
        repo.create_operation(f"op-{status}", "device-a", owners[0], "ping", {}, status=status)
    repo.update_operation("op-running", status="running", result={"bytes_done": 10})
    with closing(SqlitePool(db.path)) as restarted_db:
        fresh_repo = DeviceRepo(restarted_db)
        assert fresh_repo.recover_incomplete_operations() == 2
        assert fresh_repo.recover_incomplete_operations() == 0
        for status in statuses:
            row = fresh_repo.get_operation(f"op-{status}")
            assert row is not None
            assert row.status == ("unknown" if status in {"queued", "running"} else status)
        running = fresh_repo.get_operation("op-running")
        assert running is not None and running.result == {"bytes_done": 10}


def test_operation_constraints_reject_invalid_status_and_grant_version(
    repo: DeviceRepo, owners: tuple[int, int]
) -> None:
    create_device(repo, owners[0])
    with pytest.raises(sqlite3.IntegrityError):
        repo.create_operation("op-invalid", "device-a", owners[0], "ping", {}, status="retry")
    with pytest.raises(sqlite3.IntegrityError):
        repo.create_operation("op-invalid", "device-a", owners[0], "ping", {}, grant_version=0)
    assert repo.list_operations(owners[0]) == []


def test_migration_cascades_account_deletion_to_devices_and_operations(
    repo: DeviceRepo, db: SqlitePool, owners: tuple[int, int]
) -> None:
    create_device(repo, owners[0])
    repo.create_operation("op-a", "device-a", owners[0], "ping", {})
    with db.transaction() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (owners[0],))
    assert repo.get("device-a") is None
    assert repo.get_operation("op-a") is None


def test_migration_preserves_rows_when_applied_again(
    repo: DeviceRepo, db: SqlitePool, owners: tuple[int, int]
) -> None:
    device = create_device(repo, owners[0])
    operation = repo.create_operation("op-a", device.device_id, owners[0], "ping", {})
    run_migrations(db)
    assert repo.get(device.device_id) == device
    assert repo.get_operation(operation.operation_id) == operation
    with db.connect() as conn:
        assert conn.execute("SELECT version FROM _schema_version").fetchone()[0] == 23


def test_device_repo_is_wired_into_services(db: SqlitePool, tmp_path: Path) -> None:
    bundle = RepoBundle.from_pool(db)
    services = SharedServices(paths=PathLayout(tmp_path), config=OctopConfig(), repos=bundle)
    assert services.device_repo is bundle.device_repo
    assert isinstance(bundle.device_repo, DeviceRepo)
