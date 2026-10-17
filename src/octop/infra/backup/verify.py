"""Verify backup archives against integrity sidecars (0026 DEC-B02 / AC-B03)."""

from __future__ import annotations

import tarfile
from dataclasses import dataclass
from pathlib import Path

from octop.infra.backup.integrity import (
    IntegrityManifest,
    load_integrity_for_archive,
    save_integrity_for_archive,
    sha256_file,
)
from octop.infra.errors import ErrorCode, OctopError


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    archive: str
    message: str
    sha256: str = ""
    member_count: int = 0
    verify_status: str = "failed"


def verify_backup_archive(archive: Path, *, update_sidecar: bool = True) -> VerifyResult:
    """Hash the archive, compare to sidecar, and smoke-list tar members."""
    archive = Path(archive)
    if not archive.is_file():
        raise OctopError(ErrorCode.NOT_FOUND, f"backup not found: {archive}")

    digest = sha256_file(archive)
    manifest = load_integrity_for_archive(archive)
    member_count = 0
    try:
        with tarfile.open(archive, mode="r:*") as tf:
            # Cheap listing — do not extract.
            for _ in tf:
                member_count += 1
                if member_count > 500_000:
                    break
    except tarfile.TarError as exc:
        result = VerifyResult(
            ok=False,
            archive=archive.name,
            message=f"tar listing failed: {exc}",
            sha256=digest,
            member_count=0,
            verify_status="failed",
        )
        _maybe_update(manifest, archive, "failed", update_sidecar)
        return result

    if manifest is None:
        return VerifyResult(
            ok=False,
            archive=archive.name,
            message="integrity sidecar missing; cannot confirm sha256 (re-run backup under 0026+)",
            sha256=digest,
            member_count=member_count,
            verify_status="failed",
        )

    expected = ""
    for entry in manifest.files:
        if entry.path == archive.name or Path(entry.path).name == archive.name:
            expected = entry.sha256
            break
    if not expected and manifest.files:
        expected = manifest.files[0].sha256

    if not expected:
        _maybe_update(manifest, archive, "failed", update_sidecar)
        return VerifyResult(
            ok=False,
            archive=archive.name,
            message="integrity sidecar has no file sha256 entries",
            sha256=digest,
            member_count=member_count,
            verify_status="failed",
        )

    if expected.lower() != digest.lower():
        _maybe_update(manifest, archive, "failed", update_sidecar)
        return VerifyResult(
            ok=False,
            archive=archive.name,
            message=f"sha256 mismatch: expected {expected}, got {digest}",
            sha256=digest,
            member_count=member_count,
            verify_status="failed",
        )

    _maybe_update(manifest, archive, "ok", update_sidecar)
    return VerifyResult(
        ok=True,
        archive=archive.name,
        message="hash and tar listing ok",
        sha256=digest,
        member_count=member_count,
        verify_status="ok",
    )


def _maybe_update(
    manifest: IntegrityManifest | None,
    archive: Path,
    status: str,
    update_sidecar: bool,
) -> None:
    if not update_sidecar or manifest is None:
        return
    manifest.verify_status = status  # type: ignore[assignment]
    save_integrity_for_archive(manifest, archive)
