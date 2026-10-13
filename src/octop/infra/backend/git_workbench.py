"""Bounded Git inspection and recoverable file restore inside an agent workspace."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

MAX_OUTPUT = 512 * 1024
MAX_RESTORE_BYTES = 16 * 1024 * 1024


def _git(cwd: Path, *args: str) -> bytes:
    result = subprocess.run(
        [
            "git",
            "--no-pager",
            "--literal-pathspecs",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.quotepath=false",
            *args,
        ],
        cwd=cwd,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if result.returncode:
        raise ValueError(result.stderr.decode("utf-8", errors="replace")[:300])
    return result.stdout[: MAX_OUTPUT + 1]


def _repository(workspace: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("invalid repository path")
    workspace = workspace.resolve()
    selected = (workspace / relative).resolve()
    if not selected.is_relative_to(workspace) or not selected.is_dir():
        raise ValueError("repository is outside the workspace")
    root = Path(_git(selected, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    if not root.is_relative_to(workspace):
        raise ValueError("repository is outside the workspace")
    return root


def _changed_paths(root: Path, *args: str) -> set[str]:
    raw = _git(root, "diff", "--name-only", "-z", *args)
    if len(raw) > MAX_OUTPUT:
        raise ValueError("too many changed files")
    return {part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part}


def git_snapshot(workspace: Path, relative: str = ".") -> dict[str, object]:
    workspace = workspace.resolve()
    repositories = ["."] if (workspace / ".git").exists() else []
    if workspace.is_dir():
        repositories.extend(
            child.name
            for child in sorted(workspace.iterdir())
            if child.is_dir() and not child.is_symlink() and (child / ".git").exists()
        )
    if relative == "." and "." not in repositories:
        if repositories:
            relative = repositories[0]
        else:
            return {"available": False, "repositories": [], "reason": "no Git repository"}
    root = _repository(workspace, relative)
    status = _git(root, "status", "--short", "--branch")
    unstaged = _git(root, "diff", "--no-ext-diff", "--no-textconv", "--no-color")
    staged = _git(root, "diff", "--cached", "--no-ext-diff", "--no-textconv", "--no-color")
    dirty = _changed_paths(root)
    staged_paths = _changed_paths(root, "--cached")
    restorable = []
    for path in sorted(dirty - staged_paths):
        candidate = root / path
        file = candidate.resolve()
        if (
            file.is_file()
            and not candidate.is_symlink()
            and file.is_relative_to(root)
            and file.stat().st_size <= MAX_RESTORE_BYTES
        ):
            restorable.append({"path": path, "hash": hashlib.sha256(file.read_bytes()).hexdigest()})
    return {
        "available": True,
        "repositories": repositories,
        "path": root.relative_to(workspace).as_posix() or ".",
        "status": status.decode("utf-8", errors="replace"),
        "diff": unstaged[:MAX_OUTPUT].decode("utf-8", errors="replace"),
        "staged_diff": staged[:MAX_OUTPUT].decode("utf-8", errors="replace"),
        "truncated": len(unstaged) > MAX_OUTPUT or len(staged) > MAX_OUTPUT,
        "restorable": restorable,
    }


def restore_file(
    workspace: Path,
    relative: str,
    file_path: str,
    expected_hash: str,
    recovery_root: Path,
) -> str:
    """Restore one tracked unstaged file after saving its current bytes."""
    root = _repository(workspace, relative)
    if not file_path or Path(file_path).is_absolute() or ".." in Path(file_path).parts:
        raise ValueError("invalid file path")
    candidate = root / file_path
    file = candidate.resolve()
    if not file.is_relative_to(root) or not file.is_file() or candidate.is_symlink():
        raise ValueError("file is unavailable")
    if file.stat().st_size > MAX_RESTORE_BYTES:
        raise ValueError("file is too large to restore here")
    if file_path not in _changed_paths(root) or file_path in _changed_paths(root, "--cached"):
        raise ValueError("file is not an unstaged tracked change")
    if hashlib.sha256(file.read_bytes()).hexdigest() != expected_hash:
        raise ValueError("file changed; refresh before restoring")
    recovery_root.mkdir(parents=True, exist_ok=True)
    backup = recovery_root / f"{uuid4().hex}-{file.name}"
    shutil.copy2(file, backup)
    _git(root, "restore", "--worktree", "--", file_path)
    return str(backup)
