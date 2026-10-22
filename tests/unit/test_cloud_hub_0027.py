"""0027 S0 cloud hub runtime: loopback defaults, 90 drop-in, upgrade/rollback skeleton."""

from __future__ import annotations

import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX hub runtime scripts")

REPO = Path(__file__).resolve().parents[2]
OPS = REPO / "ops" / "cloud-hub"


def test_0027_spec_ready_s0() -> None:
    text = (REPO / "docs/specs/0027-ops-host-runtime.md").read_text(encoding="utf-8")
    assert "Status: **Ready**" in text
    assert "2026-10-17.1" in text
    assert "**S0**" in text
    assert "DEC-S01" in text
    assert "127.0.0.1" in text


@posix_only
def test_s0_artifacts_exist_and_executable() -> None:
    for name in (
        "install-hub.sh",
        "upgrade-hub.sh",
        "rollback-hub.sh",
        "_hub_common.sh",
        "smoke-hub.sh",
        "90-octop.conf.in",
        "octop-hub.octop.service.example",
        "ssh-ufw-checklist.md",
    ):
        path = OPS / name
        assert path.is_file(), name
        if name.endswith(".sh"):
            mode = path.stat().st_mode
            assert mode & stat.S_IXUSR, f"{name} should be executable"
    # git index must carry +x (100755) so clones stay runnable
    listed = subprocess.check_output(
        ["git", "ls-files", "--stage", "--", "ops/cloud-hub"],
        cwd=REPO,
        text=True,
    )
    for name in (
        "install-hub.sh",
        "upgrade-hub.sh",
        "rollback-hub.sh",
        "_hub_common.sh",
        "smoke-hub.sh",
    ):
        assert any(
            line.startswith("100755 ") and line.endswith(f"ops/cloud-hub/{name}")
            for line in listed.splitlines()
        ), f"{name} missing git +x (100755)"


def test_install_defaults_loopback_and_gates() -> None:
    text = (OPS / "install-hub.sh").read_text(encoding="utf-8")
    assert 'BIND_HOST="${OCTOP_BIND_HOST:-127.0.0.1}"' in text
    assert "--allow-public-bind" in text
    assert "--allow-root" in text
    assert "--frozen" in text
    assert "90-octop.conf" in text
    assert "hub_archive_stale_dropins" in text
    assert "hub_validate_bind_host" in text
    assert "hub_validate_service_user" in text
    # must not default to 0.0.0.0 anymore
    assert 'BIND_HOST="${OCTOP_BIND_HOST:-0.0.0.0}"' not in text


def test_dropin_clears_and_sets_execstart() -> None:
    text = (OPS / "90-octop.conf.in").read_text(encoding="utf-8")
    assert "ExecStart=" in text
    assert "ExecStart=@UV_BIN@ run octop run" in text
    assert "OCTOP_BIND_HOST=@BIND_HOST@" in text


def test_preferred_octop_example_non_root_loopback() -> None:
    text = (OPS / "octop-hub.octop.service.example").read_text(encoding="utf-8")
    assert "User=octop" in text
    assert "Group=octop" in text
    assert "OCTOP_BIND_HOST=127.0.0.1" in text
    assert "0.0.0.0" not in text


def test_upgrade_rollback_skeleton() -> None:
    upgrade = (OPS / "upgrade-hub.sh").read_text(encoding="utf-8")
    rollback = (OPS / "rollback-hub.sh").read_text(encoding="utf-8")
    assert "uv sync --frozen" in upgrade
    assert "hub_record_version" in upgrade
    assert "rollback-hub.sh" in upgrade
    assert "hub_archive_stale_dropins" in (OPS / "_hub_common.sh").read_text(encoding="utf-8")
    assert "OCTOP_HOME" in upgrade
    assert "--sha" in rollback
    assert "uv sync --frozen" in rollback
    assert "pre-upgrade" in upgrade
    assert "hub_select_rollback_meta" in rollback
    assert "hub_select_rollback_meta" in (OPS / "_hub_common.sh").read_text(encoding="utf-8")


def test_ssh_ufw_checklist_covers_ac_s04() -> None:
    text = (OPS / "ssh-ufw-checklist.md").read_text(encoding="utf-8")
    assert "PasswordAuthentication" in text
    assert "8188" in text
    assert "不对公网" in text or "Anywhere" in text
    assert "access_log" in text or "Access log" in text
    assert "90-octop" in text


def test_ops_doc_and_0009_errata() -> None:
    ops = (REPO / "docs/octopus/cloud-hub-ops.md").read_text(encoding="utf-8")
    assert "0027" in ops
    assert "--allow-public-bind" in ops
    assert "upgrade-hub.sh" in ops
    assert "rollback-hub.sh" in ops
    spec = (REPO / "docs/specs/0009-cloud-hub-production.md").read_text(encoding="utf-8")
    assert "Errata" in spec
    assert "0027-ops-host-runtime.md" in spec


@posix_only
def test_hub_validate_bind_host_helper(tmp_path: Path) -> None:
    script = textwrap.dedent(
        f"""\
        set -euo pipefail
        source "{OPS / "_hub_common.sh"}"
        hub_validate_bind_host 127.0.0.1 0
        if hub_validate_bind_host 0.0.0.0 0; then
          echo "expected refuse" >&2
          exit 1
        fi
        hub_validate_bind_host 0.0.0.0 1
        echo OK
        """
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout
    assert "refusing public bind" in proc.stderr or "WARNING" in proc.stderr


@posix_only
def test_hub_archive_stale_dropins(tmp_path: Path) -> None:
    dropin = tmp_path / "octop-hub.service.d"
    dropin.mkdir()
    (dropin / "50-old.conf").write_text("ExecStart=/bin/false\n", encoding="utf-8")
    (dropin / "90-octop.conf").write_text("ExecStart=/bin/true\n", encoding="utf-8")
    archive_root = tmp_path / "versions"
    script = textwrap.dedent(
        f"""\
        set -euo pipefail
        source "{OPS / "_hub_common.sh"}"
        hub_archive_stale_dropins "{dropin}" "{archive_root}"
        test -f "{dropin / "90-octop.conf"}"
        test ! -f "{dropin / "50-old.conf"}"
        echo OK
        """
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "OK" in proc.stdout
    archived = list(archive_root.glob("dropin-archive-*/50-old.conf"))
    assert len(archived) == 1


@posix_only
def test_hub_record_version_retention(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    script = textwrap.dedent(
        f"""\
        set -euo pipefail
        source "{OPS / "_hub_common.sh"}"
        HUB_VERSION_RETENTION=2
        hub_record_version "{repo}" "a"
        sleep 1
        hub_record_version "{repo}" "b"
        sleep 1
        hub_record_version "{repo}" "c"
        count=$(ls -1 "{repo}/.octop-hub-versions"/*.json | wc -l)
        test "$count" -eq 2
        echo OK
        """
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "HUB_VERSION_RETENTION": "2"},
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "OK" in proc.stdout


@posix_only
def test_hub_select_rollback_prefers_pre_upgrade(tmp_path: Path) -> None:
    """Without --sha, rollback must restore the latest pre-upgrade SHA, not post-upgrade/current."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "f.txt").write_text("old", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "old"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    old_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    script = textwrap.dedent(
        f"""\
        set -euo pipefail
        source "{OPS / "_hub_common.sh"}"
        hub_record_version "{repo}" "pre-upgrade"
        """
    )
    subprocess.run(["bash", "-c", script], check=True, capture_output=True, text=True)
    (repo / "f.txt").write_text("new", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "new"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    script = textwrap.dedent(
        f"""\
        set -euo pipefail
        source "{OPS / "_hub_common.sh"}"
        hub_record_version "{repo}" "post-upgrade"
        meta=$(hub_select_rollback_meta "{repo}")
        test -n "$meta"
        sha=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["git_sha"])' "$meta")
        test "$sha" = "{old_sha}"
        echo OK
        """
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "OK" in proc.stdout


@posix_only
def test_render_unit_substitutes_placeholders(tmp_path: Path) -> None:
    out = tmp_path / "unit"
    env = {
        **os.environ,
        "HUB_USER_LINE": "User=octop\n",
        "HUB_GROUP_LINE": "Group=octop\n",
        "HUB_REPO_DIR": "/home/octop/octopus",
        "HUB_ACCOUNT_HOME": "/home/octop",
        "HUB_OCTOP_HOME": "/home/octop/OctopData",
        "HUB_UV_BIN": "/home/octop/.local/bin/uv",
        "HUB_UV_DIR": "/home/octop/.local/bin",
        "HUB_BIND_HOST": "127.0.0.1",
        "HUB_PORT": "8188",
    }
    script = textwrap.dedent(
        f"""\
        set -euo pipefail
        source "{OPS / "_hub_common.sh"}"
        hub_render_unit "{OPS / "octop-hub.service.in"}" "{out}"
        """
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    text = out.read_text(encoding="utf-8")
    assert "User=octop" in text
    assert "Group=octop" in text
    assert "OCTOP_BIND_HOST=127.0.0.1" in text
    assert "@BIND_HOST@" not in text
    assert "uv run octop run" in text
