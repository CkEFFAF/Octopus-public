"""A cold offline install must preserve the local SheetJS archive path."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_vendored_sheetjs_installs_without_a_registry_cache(
    tmp_path: Path, repo_root: Path
) -> None:
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if npm is None:
        pytest.skip("Node/npm unavailable")
    dashboard = repo_root / "dashboard"
    original = json.loads((dashboard / "package-lock.json").read_text(encoding="utf-8"))
    package = {
        "name": "vendor-install-smoke",
        "version": "1.0.0",
        "dependencies": {"xlsx": "file:vendor/xlsx-0.20.3.tgz"},
    }
    lock = {
        "name": package["name"],
        "version": "1.0.0",
        "lockfileVersion": 3,
        "requires": True,
        "packages": {"": package, "node_modules/xlsx": original["packages"]["node_modules/xlsx"]},
    }
    (tmp_path / "package.json").write_text(json.dumps(package), encoding="utf-8")
    (tmp_path / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    shutil.copy2(dashboard / ".npmrc", tmp_path / ".npmrc")
    (tmp_path / "vendor").mkdir()
    shutil.copy2(dashboard / "vendor/xlsx-0.20.3.tgz", tmp_path / "vendor/xlsx-0.20.3.tgz")
    result = subprocess.run(
        [
            npm,
            "ci",
            "--offline",
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
            "--cache",
            str(tmp_path / "empty-cache"),
        ],
        cwd=tmp_path,
        env={**os.environ, "NPM_CONFIG_UPDATE_NOTIFIER": "false"},
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    installed = json.loads(
        (tmp_path / "node_modules/xlsx/package.json").read_text(encoding="utf-8")
    )
    assert installed["version"] == "0.20.3"
