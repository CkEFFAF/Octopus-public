"""Ops integrity sidecar for backup archives (0026 DEC-B02).

Separate from the in-archive ``manifest.json`` used by restore: this sidecar
lives next to the ``.tar.gz`` and records sha256, offsite status, and verify.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from octop import __version__ as OCTOP_VERSION

VerifyStatus = Literal["pending", "ok", "failed"]
OffsiteStatus = Literal["pending", "ok", "failed", "skipped"]

INTEGRITY_MANIFEST_VERSION = 1
_SIDECAR_SUFFIX = ".integrity.json"


def integrity_sidecar_path(archive: Path) -> Path:
    """Return ``<archive.name>.integrity.json`` beside *archive*."""
    archive = Path(archive)
    return archive.with_name(archive.name + _SIDECAR_SUFFIX)


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def octop_home_fingerprint(home: Path) -> str:
    """Stable short fingerprint of the data-plane root (not a secret)."""
    resolved = str(Path(home).expanduser().resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]


@dataclass
class IntegrityFileEntry:
    path: str
    size: int
    sha256: str


@dataclass
class OffsiteEntry:
    sink: str
    uri_or_label: str
    status: OffsiteStatus
    verified_at: str | None = None
    detail: str = ""


@dataclass
class IntegrityManifest:
    manifest_version: int
    backup_id: str
    created_at: str
    octop_version: str
    octop_home_fingerprint: str
    files: list[IntegrityFileEntry] = field(default_factory=list)
    offsite: list[OffsiteEntry] = field(default_factory=list)
    verify_status: VerifyStatus = "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "backup_id": self.backup_id,
            "created_at": self.created_at,
            "octop_version": self.octop_version,
            "octop_home_fingerprint": self.octop_home_fingerprint,
            "files": [asdict(f) for f in self.files],
            "offsite": [asdict(o) for o in self.offsite],
            "verify_status": self.verify_status,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntegrityManifest:
        files = [
            IntegrityFileEntry(
                path=str(row.get("path", "")),
                size=int(row.get("size", 0)),
                sha256=str(row.get("sha256", "")),
            )
            for row in (data.get("files") or [])
            if isinstance(row, dict)
        ]
        offsite = [
            OffsiteEntry(
                sink=str(row.get("sink", "")),
                uri_or_label=str(row.get("uri_or_label", "")),
                status=str(row.get("status", "pending")),  # type: ignore[arg-type]
                verified_at=row.get("verified_at"),
                detail=str(row.get("detail", "")),
            )
            for row in (data.get("offsite") or [])
            if isinstance(row, dict)
        ]
        return cls(
            manifest_version=int(data.get("manifest_version", 0)),
            backup_id=str(data.get("backup_id", "")),
            created_at=str(data.get("created_at", "")),
            octop_version=str(data.get("octop_version", "")),
            octop_home_fingerprint=str(data.get("octop_home_fingerprint", "")),
            files=files,
            offsite=offsite,
            verify_status=str(data.get("verify_status", "pending")),  # type: ignore[arg-type]
        )

    @classmethod
    def load(cls, path: Path) -> IntegrityManifest:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("integrity manifest must be a JSON object")
        return cls.from_dict(data)


def build_integrity_for_archive(
    archive: Path,
    *,
    home: Path,
    backup_id: str | None = None,
) -> IntegrityManifest:
    archive = Path(archive)
    digest = sha256_file(archive)
    return IntegrityManifest(
        manifest_version=INTEGRITY_MANIFEST_VERSION,
        backup_id=backup_id or uuid.uuid4().hex,
        created_at=datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        octop_version=str(OCTOP_VERSION),
        octop_home_fingerprint=octop_home_fingerprint(home),
        files=[
            IntegrityFileEntry(path=archive.name, size=archive.stat().st_size, sha256=digest),
        ],
        offsite=[],
        verify_status="pending",
    )


def write_integrity_sidecar(manifest: IntegrityManifest, archive: Path) -> Path:
    sidecar = integrity_sidecar_path(archive)
    sidecar.write_text(manifest.to_json(), encoding="utf-8")
    return sidecar


def load_integrity_for_archive(archive: Path) -> IntegrityManifest | None:
    sidecar = integrity_sidecar_path(archive)
    if not sidecar.is_file():
        return None
    return IntegrityManifest.load(sidecar)


def save_integrity_for_archive(manifest: IntegrityManifest, archive: Path) -> Path:
    return write_integrity_sidecar(manifest, archive)
