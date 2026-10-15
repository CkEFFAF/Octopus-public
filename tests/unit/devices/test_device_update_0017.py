"""0017 device zero-downtime update — policy, verify, stage, window/busy."""

from __future__ import annotations

import hashlib
import importlib.metadata
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from octop import __version__
from octop.config import OctopConfig
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.devices.client import DeviceClient
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
    allowed_download_hosts,
    detect_busy,
    download_and_verify,
    health_check,
    resolve_software_version,
    stage_side_by_side,
    validate_download_url,
)
from octop.infra.utils.paths import PathLayout


@pytest.mark.parametrize(
    ("package_name", "file_text", "installed_version", "environment_version", "expected"),
    [
        ("octop", " 1.2.3\nignored\n", "2.0.0", "3.0.0", "1.2.3"),
        ("octop", " \n", "2.0.0", "3.0.0", "2.0.0"),
        ("octop", None, "2.0.0", "3.0.0", "2.0.0"),
        ("octop", None, None, "3.0.0", "3.0.0"),
        ("octop", None, None, None, __version__),
        ("octop", None, None, "", __version__),
        ("other-package", None, None, None, "0.0.0"),
        ("other-package", None, None, "", "0.0.0"),
        ("other-package", None, None, "3.0.0", "3.0.0"),
    ],
)
def test_resolve_software_version_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    package_name: str,
    file_text: str | None,
    installed_version: str | None,
    environment_version: str | None,
    expected: str,
) -> None:
    def version(name: str) -> str:
        assert name == package_name
        if installed_version is None:
            raise importlib.metadata.PackageNotFoundError(name)
        return installed_version

    monkeypatch.setattr(importlib.metadata, "version", version)
    if environment_version is None:
        monkeypatch.delenv("OCTOP_SOFTWARE_VERSION", raising=False)
    else:
        monkeypatch.setenv("OCTOP_SOFTWARE_VERSION", environment_version)
    version_file = tmp_path / "version.txt"
    if file_text is not None:
        version_file.write_text(file_text, encoding="utf-8")
    assert (
        resolve_software_version(package_name=package_name, version_file=version_file) == expected
    )


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
                        "url": "https://github.com/CkEFFAF/Octopus-public/releases/download/v0.0.0/a.zip",
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
                        "url": "https://github.com/CkEFFAF/Octopus-public/releases/download/v0.0.0/a.tgz",
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
                        "url": "https://github.com/CkEFFAF/Octopus-public/releases/download/v0.0.0/a.tgz",
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
            "https://github.com/CkEFFAF/Octopus-public/releases/download/v0.0.0/pkg.bin",
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
        "https://github.com/CkEFFAF/Octopus-public/releases/download/v0.0.0/next.zip",
        expect_sha256=digest,
        dest_dir=tmp_path / "dl",
        opener=fake_open,
    )
    staged = stage_side_by_side(archived, current_dir=current, version="1.2.3")
    assert staged.resolve() != current.resolve()
    assert (staged / "app.txt").read_text(encoding="utf-8") == "new"
    # No expected binary → health must fail (not weak "dir non-empty").
    assert health_check(staged) is False
    assert health_check(staged, probe_argv=["python", "-c", "raise SystemExit(0)"]) is True


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
                        "url": "https://github.com/CkEFFAF/Octopus-public/releases/download/v0.0.0/a.zip",
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


def test_force_does_not_override_busy() -> None:
    """force ignores deferrable, but busy+skip_when_busy still blocks cutover."""
    policy = parse_policy(
        {
            "target_version": "1.0.0",
            "force": True,
            "deferrable": True,
            "skip_when_busy": True,
            "window_local": {"start_hour": 0, "end_hour": 24},
            "manifest": {
                "assets": [
                    {
                        "platform": "linux-amd64",
                        "kind": "device",
                        "url": "https://github.com/CkEFFAF/Octopus-public/releases/download/v0.0.0/a.tgz",
                        "sha256": "x",
                    }
                ]
            },
        }
    )
    now = datetime(2026, 10, 15, 3, 0, tzinfo=ZoneInfo("UTC"))
    assert may_cutover(policy, busy=True, deferred=True, now=now) is False
    assert may_cutover(policy, busy=False, deferred=True, now=now) is True


def test_reject_non_https_download_url(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="https"):
        validate_download_url("http://example.com/pkg.bin")
    with pytest.raises(ValueError, match="https"):
        download_and_verify(
            "http://example.com/pkg.bin",
            expect_sha256="00" * 32,
            dest_dir=tmp_path / "dl",
            opener=lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not open")),
        )


def test_client_consumes_pending_update_offer(tmp_path: Path) -> None:
    install = tmp_path / "current"
    install.mkdir()
    (install / "keep.txt").write_text("old", encoding="utf-8")
    zpath = tmp_path / "next.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("pkg/octop", "payload")
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

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    client = DeviceClient(state_dir)
    client._pending_update_offer = {
        "type": "device_update.offer",
        "target_version": "1.2.3",
        "channel": "stable",
        "window_local": {"start_hour": 0, "end_hour": 24},
        "force": False,
        "deferrable": True,
        "skip_when_busy": True,
        "asset": {
            "url": "https://github.com/CkEFFAF/Octopus-public/releases/download/v0.0.0/next.zip",
            "sha256": digest,
            "platform": "linux-amd64",
            "kind": "device",
        },
    }

    import octop.infra.devices.updater as updater_mod

    real_download = updater_mod.download_and_verify
    real_health = updater_mod.health_check

    def wrapped(url, *, expect_sha256, dest_dir, filename=None, opener=None):
        return real_download(
            url,
            expect_sha256=expect_sha256,
            dest_dir=dest_dir,
            filename=filename,
            opener=fake_open,
        )

    updater_mod.download_and_verify = wrapped  # type: ignore[assignment]
    updater_mod.health_check = lambda *a, **k: True  # type: ignore[assignment]
    try:
        now = datetime(2026, 10, 15, 3, 0, tzinfo=ZoneInfo("UTC"))
        # Busy → stage only, offer kept for retry
        report = client.consume_pending_update_offer(
            busy=True,
            install_dir=install,
            now=now,
        )
        assert report is not None
        assert report["status"] == "staged"
        assert client._pending_update_offer is not None

        # Idle → cutover completes and clears pending offer
        report2 = client.consume_pending_update_offer(
            busy=False,
            install_dir=install,
            now=now,
        )
        assert report2 is not None
        assert report2["status"] == "ok"
        assert report2["software_version"] == "1.2.3"
        assert client._pending_update_offer is None
    finally:
        updater_mod.download_and_verify = real_download  # type: ignore[assignment]
        updater_mod.health_check = real_health  # type: ignore[assignment]


def test_force_does_not_bypass_window() -> None:
    """force ignores deferrable / enables pre-download, but never cutover outside window."""
    policy = parse_policy(
        {
            "target_version": "1.0.0",
            "force": True,
            "deferrable": True,
            "skip_when_busy": True,
            "window_local": {"start_hour": 0, "end_hour": 8},
            "manifest": {
                "assets": [
                    {
                        "platform": "linux-amd64",
                        "kind": "device",
                        "url": "https://github.com/CkEFFAF/Octopus-public/releases/download/v0.0.0/a.tgz",
                        "sha256": "x",
                    }
                ]
            },
        }
    )
    noon = datetime(2026, 10, 15, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    early = datetime(2026, 10, 15, 3, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert may_cutover(policy, busy=False, deferred=True, now=noon) is False
    assert may_cutover(policy, busy=False, deferred=True, now=early) is True
    # Prior rule still holds: force + in-window + busy + skip_when_busy -> False
    assert may_cutover(policy, busy=True, deferred=True, now=early) is False


def test_reject_non_allowlisted_download_host() -> None:
    with pytest.raises(ValueError, match="host not allowed"):
        validate_download_url("https://evil.example/pkg.bin")
    assert "github.com" in allowed_download_hosts()
    validate_download_url(
        "https://github.com/CkEFFAF/Octopus-public/releases/download/v1.0.0/x.zip"
    )


def test_hello_connect_persists_software_version(tmp_path: Path) -> None:
    import asyncio

    from octop.infra.devices.service import DeviceService

    services = _services(tmp_path)
    service = DeviceService(services.repos)
    owner = services.repos.user_repo.create(username="admin", password_hash="x", role="admin")
    enrolled = service.enroll(
        pairing_code=service.pairing(owner)["pairing_code"],
        name="hello-sw",
        platform="linux",
        capabilities=["files_read"],
        permissions=["files_read"],
        roots=[],
    )
    device_id = enrolled["device"]["device_id"]
    token = enrolled["device_token"]
    sent: list[dict] = []

    async def send(frame):
        sent.append(frame)

    async def close():
        return None

    async def run():
        return await service.connect(
            device_id,
            token,
            send,
            close,
            software_version="1.4.2",
        )

    asyncio.run(run())
    row = services.repos.device_repo.get(device_id)
    assert row is not None
    assert row.software_version == "1.4.2"
