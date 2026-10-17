"""0026 S0: integrity sidecar, offsite hook, verify, alerts."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest

from octop.config import BackupConfig, BackupOffsiteConfig, load_config
from octop.infra.backup.alerts import (
    AlertSettings,
    check_disk_and_alert,
    disk_free_percent,
    emit_alert,
)
from octop.infra.backup.auto import finalize_backup_artifact
from octop.infra.backup.integrity import (
    build_integrity_for_archive,
    integrity_sidecar_path,
    load_integrity_for_archive,
    save_integrity_for_archive,
    sha256_file,
)
from octop.infra.backup.offsite import OffsiteSinkSettings, run_offsite
from octop.infra.backup.store import BackupFileInfo, delete_backup_file
from octop.infra.backup.verify import verify_backup_archive
from octop.infra.errors import OctopError
from octop.infra.utils.paths import PathLayout


def _tiny_archive(path: Path, payload: bytes = b"hello-backup") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as tf:
        info = tarfile.TarInfo(name="manifest.json")
        data = json.dumps(
            {
                "manifest_version": 1,
                "octop_version": "test",
                "schema_version": 1,
                "created_at": "2026-10-17T00:00:00Z",
                "home": "/tmp",
            }
        ).encode()
        info.size = len(data)
        import io

        tf.addfile(info, io.BytesIO(data))
        info2 = tarfile.TarInfo(name="payload.bin")
        info2.size = len(payload)
        tf.addfile(info2, io.BytesIO(payload))
    return path


def test_sha256_and_integrity_sidecar(tmp_path: Path) -> None:
    archive = _tiny_archive(tmp_path / "octop-auto-backup-20261017T000000Z.tar.gz")
    manifest = build_integrity_for_archive(archive, home=tmp_path)
    assert manifest.files[0].sha256 == sha256_file(archive)
    save_integrity_for_archive(manifest, archive)
    assert integrity_sidecar_path(archive).is_file()
    loaded = load_integrity_for_archive(archive)
    assert loaded is not None
    assert loaded.backup_id == manifest.backup_id


def test_verify_ok_and_mismatch(tmp_path: Path) -> None:
    archive = _tiny_archive(tmp_path / "octop-backup-20261017T000000Z.tar.gz")
    manifest = build_integrity_for_archive(archive, home=tmp_path)
    save_integrity_for_archive(manifest, archive)
    ok = verify_backup_archive(archive)
    assert ok.ok
    assert ok.verify_status == "ok"

    # Corrupt sidecar hash
    manifest.files[0].sha256 = "0" * 64
    save_integrity_for_archive(manifest, archive)
    bad = verify_backup_archive(archive)
    assert not bad.ok


def test_offsite_hook_success_and_failure(tmp_path: Path) -> None:
    archive = _tiny_archive(tmp_path / "a.tar.gz")
    marker = tmp_path / "copied"
    script = tmp_path / "copy.sh"
    script.write_text('#!/bin/sh\ncp "$1" "$2"\n', encoding="utf-8")
    script.chmod(0o755)

    settings = OffsiteSinkSettings(
        enabled=True,
        type="hook",
        hook_argv=(str(script), "{archive}", str(marker)),
    )
    result = run_offsite(archive, settings, backup_id="bid")
    assert result.ok
    assert result.entry.status == "ok"
    assert marker.is_file()

    fail = OffsiteSinkSettings(
        enabled=True,
        type="hook",
        hook_argv=("/bin/false",),
    )
    failed = run_offsite(archive, fail, backup_id="bid")
    assert not failed.ok
    assert failed.entry.status == "failed"


def test_offsite_disabled_is_skipped(tmp_path: Path) -> None:
    archive = _tiny_archive(tmp_path / "a.tar.gz")
    result = run_offsite(archive, OffsiteSinkSettings(enabled=False))
    assert result.ok
    assert result.entry.status == "skipped"


def test_finalize_marks_failed_when_offsite_fails(tmp_path: Path) -> None:
    home = tmp_path / "OctopData"
    backups = home / "backups"
    backups.mkdir(parents=True)
    archive = _tiny_archive(backups / "octop-auto-backup-20261017T010000Z.tar.gz")
    paths = PathLayout(home)
    entry = BackupFileInfo(
        name=archive.name,
        size=archive.stat().st_size,
        modified_at="2026-10-17T01:00:00+00:00",
        created_at="2026-10-17T01:00:00+00:00",
    )
    backup = BackupConfig(
        retention_count=14,
        offsite=BackupOffsiteConfig(enabled=True, type="hook", hook_argv=["/bin/false"]),
        alert_webhook_url="",
    )
    with pytest.raises(OctopError):
        finalize_backup_artifact(paths=paths, entry=entry, backup=backup)
    side = load_integrity_for_archive(archive)
    assert side is not None
    assert side.offsite[0].status == "failed"


def test_retention_default_is_14() -> None:
    assert BackupConfig().retention_count == 14


def test_load_config_parses_offsite(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "backup": {
                    "retention_count": 14,
                    "alert_webhook_url": "http://127.0.0.1:9/hook",
                    "offsite": {
                        "enabled": True,
                        "type": "hook",
                        "hook_argv": ["echo", "{archive}"],
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    loaded = load_config(cfg)
    assert loaded.backup.retention_count == 14
    assert loaded.backup.offsite.enabled is True
    assert loaded.backup.offsite.hook_argv == ["echo", "{archive}"]
    assert loaded.backup.alert_webhook_url.startswith("http://")


def test_emit_alert_without_webhook_logs(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    with caplog.at_level(logging.ERROR):
        delivery = emit_alert(AlertSettings(webhook_url=""), "backup_failed", "boom")
    assert delivery.delivered is False
    assert "boom" in caplog.text


def test_delete_removes_sidecar(tmp_path: Path) -> None:
    home = tmp_path / "home"
    backups = home / "backups"
    backups.mkdir(parents=True)
    archive = _tiny_archive(backups / "octop-auto-backup-20261017T020000Z.tar.gz")
    save_integrity_for_archive(build_integrity_for_archive(archive, home=home), archive)
    assert integrity_sidecar_path(archive).is_file()
    delete_backup_file(PathLayout(home), archive.name)
    assert not archive.exists()
    assert not integrity_sidecar_path(archive).exists()


def test_disk_free_percent_positive(tmp_path: Path) -> None:
    assert disk_free_percent(tmp_path) > 0


def test_check_disk_alert_when_threshold_absurdly_high(tmp_path: Path) -> None:
    # Threshold 100.1% means any real free% is "low".
    delivery = check_disk_and_alert(
        AlertSettings(webhook_url="", disk_free_percent_min=100.1),
        home=tmp_path,
    )
    assert delivery is not None
    assert delivery.kind == "disk_low"
