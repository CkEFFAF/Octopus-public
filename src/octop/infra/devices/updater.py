"""Device-side zero-downtime update helpers (0017) — download/verify/stage/health/cutover."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import tarfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import urlopen

logger = logging.getLogger(__name__)

BusyProbe = Callable[[], tuple[bool, list[str]]]


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()



def validate_download_url(url: str) -> None:
    """Reject non-https package URLs (0017 iron rule: Hub-issued official HTTPS only)."""
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise ValueError("download URL must be https")
    if not parsed.hostname:
        raise ValueError("download URL missing host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("download URL must not contain credentials")


def download_and_verify(
    url: str,
    *,
    expect_sha256: str,
    dest_dir: Path,
    filename: str | None = None,
    opener: Callable[..., Any] | None = None,
) -> Path:
    """Download *url* into *dest_dir* and verify SHA256. Raises ValueError on mismatch."""
    validate_download_url(url)
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = filename or url.rstrip("/").split("/")[-1] or "package.bin"
    tmp = dest_dir / f".{name}.partial"
    final = dest_dir / name
    open_url = opener or urlopen
    with open_url(url, timeout=120) as resp, tmp.open("wb") as out:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
    actual = sha256_file(tmp)
    expect = expect_sha256.strip().lower()
    if actual != expect:
        tmp.unlink(missing_ok=True)
        raise ValueError(f"sha256 mismatch: expected {expect}, got {actual}")
    tmp.replace(final)
    return final



def _is_within_directory(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _safe_zip_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    for info in zf.infolist():
        name = info.filename
        if not name or name.endswith("/"):
            continue
        target = (dest / name).resolve()
        if not _is_within_directory(dest, target):
            raise ValueError(f"zip path traversal blocked: {name}")
    zf.extractall(dest)


def _safe_tar_extract(tf: tarfile.TarFile, dest: Path) -> None:
    for member in tf.getmembers():
        name = member.name
        if not name:
            continue
        target = (dest / name).resolve()
        if not _is_within_directory(dest, target):
            raise ValueError(f"tar path traversal blocked: {name}")
        if member.issym() or member.islnk():
            link = member.linkname or ""
            if Path(link).is_absolute():
                raise ValueError(f"tar link traversal blocked: {name}")
            link_target = (dest / Path(name).parent / link).resolve()
            if not _is_within_directory(dest, link_target):
                raise ValueError(f"tar link traversal blocked: {name}")
    # Prefer filter="data" (3.11.4+/3.12+) to block .. / abs / specials.
    try:
        tf.extractall(dest, filter="data")
    except TypeError:
        tf.extractall(dest)


def stage_side_by_side(
    archive: Path,
    *,
    current_dir: Path,
    version: str,
    releases_root: Path | None = None,
) -> Path:
    """Extract *archive* into a sibling stage directory (never overwrite *current_dir*)."""
    root = releases_root or current_dir.parent
    stage = root / "releases" / version
    if stage.resolve() == current_dir.resolve():
        raise ValueError("stage directory must differ from current install directory")
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            _safe_zip_extract(zf, stage)
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tf:
            _safe_tar_extract(tf, stage)
    else:
        # Treat as a single binary/dir payload: copy into stage root.
        target = stage / archive.name
        shutil.copy2(archive, target)
    # Flatten single top-level directory if present.
    children = [p for p in stage.iterdir() if not p.name.startswith(".")]
    if len(children) == 1 and children[0].is_dir():
        nested = children[0]
        for item in nested.iterdir():
            shutil.move(str(item), str(stage / item.name))
        nested.rmdir()
    if stage.resolve() == current_dir.resolve():
        raise ValueError("stage path collided with current")
    return stage


def health_check(
    staged_dir: Path,
    *,
    probe_argv: list[str] | None = None,
    timeout: float = 30.0,
) -> bool:
    """Run a version/probe command against the staged install. Returns True on success."""
    if probe_argv is None:
        candidates = [
            staged_dir / "Octop.exe",
            staged_dir / "octop.exe",
            staged_dir / "octop",
            staged_dir / "bin" / "octop",
            staged_dir / "Octop-device",
        ]
        binary = next((c for c in candidates if c.exists()), None)
        if binary is None:
            logger.warning("health_check: no expected binary under %s", staged_dir)
            return False
        probe_argv = [str(binary), "--version"]
    try:
        completed = subprocess.run(
            probe_argv,
            cwd=str(staged_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("health_check failed: %s", exc)
        return False
    return completed.returncode == 0


def rollback_stage(staged_dir: Path) -> None:
    if staged_dir.exists():
        shutil.rmtree(staged_dir, ignore_errors=True)


def cutover(
    *,
    current_link: Path,
    staged_dir: Path,
    previous_link: Path | None = None,
) -> None:
    """Atomically point *current_link* at *staged_dir* (symlink or junction-style marker).

    On platforms without symlink privilege, write a ``current.txt`` pointer file next to
    the link path instead of failing hard.
    """
    current_link.parent.mkdir(parents=True, exist_ok=True)
    if previous_link is not None and current_link.exists():
        if previous_link.exists() or previous_link.is_symlink():
            if previous_link.is_dir() and not previous_link.is_symlink():
                shutil.rmtree(previous_link, ignore_errors=True)
            else:
                previous_link.unlink(missing_ok=True)
        try:
            previous_link.symlink_to(current_link.resolve(), target_is_directory=True)
        except OSError:
            previous_link.write_text(str(current_link.resolve()), encoding="utf-8")
    # Replace current pointer.
    if current_link.exists() or current_link.is_symlink():
        if current_link.is_dir() and not current_link.is_symlink():
            # Directory install: swap via rename dance into sibling.
            backup = current_link.with_name(current_link.name + ".bak")
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            current_link.rename(backup)
            try:
                shutil.copytree(staged_dir, current_link)
            except Exception:
                if backup.exists():
                    backup.rename(current_link)
                raise
            shutil.rmtree(backup, ignore_errors=True)
            return
        current_link.unlink()
    try:
        current_link.symlink_to(staged_dir.resolve(), target_is_directory=True)
    except OSError:
        pointer = current_link if current_link.suffix else current_link.with_suffix(".txt")
        if pointer != current_link and current_link.exists():
            current_link.unlink(missing_ok=True)
        marker = (
            current_link
            if current_link.name.endswith(".txt")
            else current_link.parent / "current.txt"
        )
        marker.write_text(str(staged_dir.resolve()), encoding="utf-8")


def detect_busy(
    *,
    active_acp_sessions: int = 0,
    pending_commands: int = 0,
    desktop_control_active: bool = False,
    active_transfers: int = 0,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if active_acp_sessions > 0:
        reasons.append("acp_session")
    if pending_commands > 0:
        reasons.append("command_run")
    if desktop_control_active:
        reasons.append("desktop_control")
    if active_transfers > 0:
        reasons.append("file_transfer")
    return (bool(reasons), reasons)


def resolve_software_version(
    *,
    package_name: str = "octop",
    version_file: Path | None = None,
) -> str:
    if version_file is not None and version_file.is_file():
        text = version_file.read_text(encoding="utf-8").strip()
        if text:
            return text.splitlines()[0].strip()
    try:
        from importlib.metadata import version

        return version(package_name)
    except Exception:
        return os.environ.get("OCTOP_SOFTWARE_VERSION", "0.0.0")


class DeviceUpdater:
    """Orchestrates download → stage → health → (optional) cutover for one device install."""

    def __init__(
        self,
        *,
        install_dir: Path,
        download_dir: Path | None = None,
        busy_probe: BusyProbe | None = None,
    ) -> None:
        self.install_dir = install_dir
        self.download_dir = download_dir or (install_dir.parent / "update-cache")
        self.busy_probe = busy_probe or (lambda: (False, []))

    def apply_offer(
        self,
        offer: dict[str, Any],
        *,
        allow_cutover: bool,
    ) -> dict[str, Any]:
        """Synchronous apply path used by unit tests and device client."""
        asset = offer.get("asset") or {}
        url = str(asset.get("url") or "")
        sha = str(asset.get("sha256") or "")
        version = str(offer.get("target_version") or "")
        if not url or not sha or not version:
            return {"status": "failed", "error": "incomplete offer"}
        try:
            archive = download_and_verify(url, expect_sha256=sha, dest_dir=self.download_dir)
        except ValueError as exc:
            return {
                "status": "failed",
                "error": str(exc),
                "software_version": resolve_software_version(),
            }
        except Exception as exc:
            return {"status": "failed", "error": f"download failed: {exc}"}
        try:
            staged = stage_side_by_side(archive, current_dir=self.install_dir, version=version)
        except Exception as exc:
            return {"status": "failed", "error": f"stage failed: {exc}"}
        if not health_check(staged):
            rollback_stage(staged)
            return {"status": "failed", "error": "health", "stage_version": version}
        busy, reasons = self.busy_probe()
        # Defense in depth: skip_when_busy always blocks cutover even if caller
        # passed allow_cutover=True (force must not override busy — 0017).
        if offer.get("skip_when_busy") and busy:
            return {
                "status": "staged",
                "stage_version": version,
                "busy": True,
                "busy_reasons": reasons,
            }
        if not allow_cutover:
            return {
                "status": "staged",
                "stage_version": version,
                "busy": busy,
                "busy_reasons": reasons,
            }
        try:
            current_link = self.install_dir.parent / "current"
            cutover(
                current_link=current_link,
                staged_dir=staged,
                previous_link=self.install_dir.parent / "previous",
            )
        except Exception as exc:
            rollback_stage(staged)
            return {"status": "rolled_back", "error": f"cutover failed: {exc}"}
        return {"status": "ok", "software_version": version, "stage_version": version}


__all__ = [
    "DeviceUpdater",
    "cutover",
    "detect_busy",
    "download_and_verify",
    "validate_download_url",
    "health_check",
    "resolve_software_version",
    "rollback_stage",
    "sha256_file",
    "stage_side_by_side",
]
