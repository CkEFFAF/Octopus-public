"""0017 device zero-downtime update — policy, verify, stage, window/busy."""

from __future__ import annotations

import hashlib
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from octop.config import OctopConfig
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.devices.update_policy import (
    batch_eligible,
    build_offer,
    in_local_window,
    load_policy_from_settings,
    may_cutover,
    parse_policy,
    save_policy_to_settings,
)
from octop.infra.devices.updater import (
    detect_busy,
    download_and_verify,
    health_check,
    stage_side_by_side,
)
from octop.infra.utils.paths import PathLayout


def _services(tmp_path: Path):
    db = SqlitePool(tmp_path / "octop.db")
    run_migrations(db)
    return build_shared_services(db=db, paths=PathLayout(tmp_path), config=OctopConfig())


def test_parse_policy_roundtrip_and_admin_store(tmp_path: Path) -> None:
    services = _services(tmp_path)
    policy = parse_policy(
        {
            "target_version": "1.2.3",
            "channel": "stable",
            "window_local": {"start_hour": 0, "end_hour": 8},
            "batch_percent": 100,
            "manifest": {
                "version": "1.2.3",
                "assets": [
                    {
                        "platform": "windows-amd64",
                        "kind": "portable",
                        "url": "https://example.com/a.zip",
                        "sha256": "abc",
                    }
                ],
            },
        }
    )
    save_policy_to_settings(services.settings_repo.set, policy)
    loaded = load_policy_from_settings(services.settings_repo.get)
    assert loaded.target_version == "1.2.3"
    assert loaded.window_local.start_hour == 0
    assert loaded.window_local.end_hour == 8


def test_reject_overnight_window() -> None:
    with pytest.raises(ValueError, match="overnight"):
        parse_policy({"window_local": {"start_hour": 22, "end_hour": 6}})


def test_batch_percent_gates() -> None:
    assert batch_eligible("dev-1", 0) is False
    assert batch_eligible("dev-1", 100) is True


def test_window_blocks_cutover_outside() -> None:
    policy = parse_policy(
        {
            "target_version": "1.0.0",
            "window_local": {"start_hour": 0, "end_hour": 8},
            "manifest": {
                "assets": [
                    {
                        "platform": "linux-amd64",
                        "kind": "device",
                        "url": "https://example.com/a.tgz",
                        "sha256": "deadbeef",
                    }
                ]
            },
        }
    )
    noon = datetime(2026, 10, 15, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert in_local_window(policy.window_local, now=noon) is False
    assert may_cutover(policy, busy=False, now=noon) is False
    early = datetime(2026, 10, 15, 3, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert may_cutover(policy, busy=False, now=early) is True


def test_busy_skips_cutover() -> None:
    policy = parse_policy(
        {
            "target_version": "1.0.0",
            "skip_when_busy": True,
            "window_local": {"start_hour": 0, "end_hour": 24},
            "manifest": {
                "assets": [
                    {
                        "platform": "linux-amd64",
                        "kind": "device",
                        "url": "https://example.com/a.tgz",
                        "sha256": "x",
                    }
                ]
            },
        }
    )
    now = datetime(2026, 10, 15, 3, 0, tzinfo=ZoneInfo("UTC"))
    assert may_cutover(policy, busy=True, now=now) is False
    busy, reasons = detect_busy(active_acp_sessions=1)
    assert busy and "acp_session" in reasons


def test_download_hash_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"hello-zdu"
    archive = tmp_path / "pkg.bin"
    archive.write_bytes(payload)

    class _Resp:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def read(self, n: int = -1) -> bytes:
            if not self._data:
                return b""
            chunk, self._data = self._data, b""
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_open(url: str, timeout: float = 120):
        return _Resp(payload)

    with pytest.raises(ValueError, match="sha256 mismatch"):
        download_and_verify(
            "https://example.com/pkg.bin",
            expect_sha256="00" * 32,
            dest_dir=tmp_path / "dl",
            opener=fake_open,
        )


def test_download_verify_and_stage_side_by_side(tmp_path: Path) -> None:
    current = tmp_path / "current"
    current.mkdir()
    (current / "keep.txt").write_text("old", encoding="utf-8")
    zpath = tmp_path / "next.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("Octop-next/app.txt", "new")
    digest = hashlib.sha256(zpath.read_bytes()).hexdigest()

    class _Resp:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def read(self, n: int = -1) -> bytes:
            out, self._data = self._data, b""
            return out

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_open(url: str, timeout: float = 120):
        return _Resp(zpath.read_bytes())

    archived = download_and_verify(
        "https://example.com/next.zip",
        expect_sha256=digest,
        dest_dir=tmp_path / "dl",
        opener=fake_open,
    )
    staged = stage_side_by_side(archived, current_dir=current, version="1.2.3")
    assert staged.resolve() != current.resolve()
    assert (staged / "app.txt").read_text(encoding="utf-8") == "new"
    assert health_check(staged) is True


def test_build_offer_filters_batch_and_platform() -> None:
    policy = parse_policy(
        {
            "target_version": "9.9.9",
            "batch_percent": 0,
            "manifest": {
                "assets": [
                    {
                        "platform": "windows-amd64",
                        "kind": "portable",
                        "url": "https://example.com/a.zip",
                        "sha256": "ab",
                    }
                ]
            },
        }
    )
    assert build_offer(policy, device_id="d1", platform="windows-amd64") is None
    policy100 = parse_policy({**policy.to_dict(), "batch_percent": 100})
    offer = build_offer(policy100, device_id="d1", platform="windows-amd64")
    assert offer is not None
    assert offer["target_version"] == "9.9.9"
    assert offer["asset"]["sha256"] == "ab"


def test_device_repo_update_report(tmp_path: Path) -> None:
    services = _services(tmp_path)
    user_id = services.repos.user_repo.create(username="admin", password_hash="x", role="admin")
    row = services.repos.device_repo.create(
        device_id="dev-zdu-1",
        owner_user_id=user_id,
        name="box",
        platform="windows-amd64",
        capabilities=["files_read"],
        permissions=["files_read"],
        roots=[],
        token_hash="abc",
    )
    updated = services.repos.device_repo.set_update_report(
        row.device_id,
        status="ok",
        software_version="1.2.3",
    )
    assert updated.software_version == "1.2.3"
    assert updated.update_status == "ok"
    pub = updated.public()
    assert pub["software_version"] == "1.2.3"
