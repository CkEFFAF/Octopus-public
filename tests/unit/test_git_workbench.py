from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from octop.infra.backend.git_workbench import git_snapshot, restore_file
from octop.infra.devices.executor import DeviceExecutor

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git unavailable")


@pytest.fixture(autouse=True)
def isolate_git_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # Hooks export these variables; otherwise temporary repos target the caller's index.
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX"):
        monkeypatch.delenv(name, raising=False)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_git_snapshot_and_recoverable_restore(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _git(root, "init")
    file = root / "note.txt"
    file.write_text("before\n")
    _git(root, "add", "note.txt")
    _git(root, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "start")
    file.write_text("after\n")

    snapshot = git_snapshot(tmp_path)
    assert snapshot["available"] is True
    assert "after" in str(snapshot["diff"])
    expected = hashlib.sha256(file.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="changed"):
        restore_file(tmp_path, "project", "note.txt", "wrong", tmp_path / "recovery")
    assert file.read_text() == "after\n"

    backup = restore_file(tmp_path, "project", "note.txt", expected, tmp_path / "recovery")
    assert file.read_text() == "before\n"
    assert Path(backup).read_text() == "after\n"


def test_git_snapshot_rejects_parent_repository(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "subdir").mkdir()
    with pytest.raises(ValueError, match="outside the workspace"):
        git_snapshot(workspace, "subdir")


def test_git_snapshot_reports_staged_and_unstaged_diffs_separately(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _git(root, "init")
    (root / "staged.txt").write_text("old staged\n")
    (root / "unstaged.txt").write_text("old unstaged\n")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "start")
    (root / "staged.txt").write_text("new staged\n")
    _git(root, "add", "staged.txt")
    (root / "unstaged.txt").write_text("new unstaged\n")

    snapshot = git_snapshot(tmp_path)

    assert snapshot["path"] == "project"
    assert "new staged" in str(snapshot["staged_diff"])
    assert "new staged" not in str(snapshot["diff"])
    assert "new unstaged" in str(snapshot["diff"])
    assert "new unstaged" not in str(snapshot["staged_diff"])
    assert [item["path"] for item in snapshot["restorable"]] == ["unstaged.txt"]


def test_git_snapshot_without_repository_is_unavailable(tmp_path: Path) -> None:
    assert git_snapshot(tmp_path) == {
        "available": False,
        "repositories": [],
        "reason": "no Git repository",
    }


def test_restore_rejects_staged_and_parent_paths(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _git(root, "init")
    file = root / "note.txt"
    file.write_text("before\n")
    _git(root, "add", "note.txt")
    _git(root, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "start")
    file.write_text("after\n")
    expected = hashlib.sha256(file.read_bytes()).hexdigest()
    _git(root, "add", "note.txt")

    with pytest.raises(ValueError, match="not an unstaged tracked change"):
        restore_file(tmp_path, "project", "note.txt", expected, tmp_path / "recovery")
    with pytest.raises(ValueError, match="invalid file path"):
        restore_file(tmp_path, "project", "../note.txt", expected, tmp_path / "recovery")
    assert file.read_text() == "after\n"
    assert not (tmp_path / "recovery").exists()


def test_restore_treats_special_filename_as_literal(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    for name in ("[ab].txt", "a.txt", "b.txt"):
        (tmp_path / name).write_text("before\n")
    _git(tmp_path, "add", ".")
    _git(
        tmp_path,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "start",
    )
    for name in ("[ab].txt", "a.txt", "b.txt"):
        (tmp_path / name).write_text("after\n")
    target = tmp_path / "[ab].txt"
    backup = restore_file(
        tmp_path,
        ".",
        target.name,
        hashlib.sha256(target.read_bytes()).hexdigest(),
        tmp_path / "recovery",
    )
    assert target.read_text() == "before\n"
    assert Path(backup).read_text() == "after\n"
    assert (tmp_path / "a.txt").read_text() == "after\n"
    assert (tmp_path / "b.txt").read_text() == "after\n"


async def test_owner_device_git_inspects_and_restores_native_repository(tmp_path: Path) -> None:
    workspace = tmp_path / "default-directory"
    workspace.mkdir()
    root = tmp_path / "outside-repository"
    root.mkdir()
    _git(root, "init")
    file = root / "note.txt"
    file.write_text("before\n")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "start")
    file.write_text("after\n")
    permissions = ["files_read", "files_write"]
    executor = DeviceExecutor(
        permissions,
        [],
        trust_mode="owner",
        working_dir=str(workspace),
        state_dir=tmp_path / "state",
    )
    try:
        snapshot = await executor.execute(
            "inspect",
            "git.snapshot",
            {"repository": str(root)},
            grant_version=0,
            permissions=permissions,
        )
        assert snapshot["path"] == str(root.resolve())
        assert "after" in snapshot["diff"]
        assert executor._journal["inspect"]["result_retained"] is False
        result = await executor.execute(
            "restore",
            "git.restore",
            {
                "repository": str(root),
                "path": "note.txt",
                "expected_hash": hashlib.sha256(file.read_bytes()).hexdigest(),
            },
            grant_version=0,
            permissions=permissions,
        )
        assert file.read_text() == "before\n"
        assert Path(result["recovery_copy"]).read_text() == "after\n"
    finally:
        await executor.close()


def test_native_git_resolves_repository_above_default_directory(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    nested = tmp_path / "data"
    nested.mkdir()
    snapshot = git_snapshot(nested, native=True)
    assert snapshot["available"] is True
    assert snapshot["path"] == str(tmp_path.resolve())
