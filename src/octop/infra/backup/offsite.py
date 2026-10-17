"""Pluggable offsite backup sinks (0026 DEC-B01 / DEC-B10).

S0 supports ``hook`` and ``rsync``. ``s3_compatible`` is reserved and rejected
with a clear error until S1+.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from octop.infra.backup.integrity import OffsiteEntry
from octop.infra.errors import ErrorCode, OctopError

logger = logging.getLogger(__name__)

_VALID_TYPES = frozenset({"hook", "rsync", "s3_compatible"})


@dataclass(frozen=True)
class OffsiteSinkSettings:
    """Runtime view of offsite settings (from BackupConfig / env)."""

    enabled: bool = False
    type: str = "hook"
    hook_argv: tuple[str, ...] = ()
    rsync_target: str = ""
    rsync_extra_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class OffsiteResult:
    entry: OffsiteEntry
    ok: bool


def _utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _expand_argv(
    template: list[str] | tuple[str, ...], *, archive: Path, integrity: Path | None, backup_id: str
) -> list[str]:
    mapping = {
        "{archive}": str(archive),
        "{integrity}": str(integrity) if integrity is not None else "",
        "{backup_id}": backup_id,
        "{archive_name}": archive.name,
    }

    def one(token: str) -> str:
        out = token
        for key, value in mapping.items():
            out = out.replace(key, value)
        return out

    return [one(t) for t in template]


def run_offsite(
    archive: Path,
    settings: OffsiteSinkSettings,
    *,
    integrity_path: Path | None = None,
    backup_id: str = "",
) -> OffsiteResult:
    """Copy *archive* (and optional integrity sidecar) to the configured sink.

    Returns an ``OffsiteResult``. When ``settings.enabled`` is false, status is
    ``skipped`` and ``ok`` is True (local-only backup is allowed).
    """
    archive = Path(archive)
    if not settings.enabled:
        return OffsiteResult(
            entry=OffsiteEntry(
                sink="none",
                uri_or_label="",
                status="skipped",
                verified_at=_utc_now(),
                detail="offsite disabled",
            ),
            ok=True,
        )

    sink_type = (settings.type or "hook").strip().lower()
    if sink_type not in _VALID_TYPES:
        raise OctopError(ErrorCode.SLASH_BAD_ARGS, f"unsupported offsite type: {sink_type!r}")
    if sink_type == "s3_compatible":
        raise OctopError(
            ErrorCode.SLASH_BAD_ARGS,
            "offsite type s3_compatible is not implemented in 0026 S0; use hook or rsync",
        )

    try:
        if sink_type == "hook":
            entry = _run_hook(archive, settings, integrity_path=integrity_path, backup_id=backup_id)
        else:
            entry = _run_rsync(archive, settings, integrity_path=integrity_path)
    except OctopError as exc:
        return OffsiteResult(
            entry=OffsiteEntry(
                sink=sink_type,
                uri_or_label=_label_for(settings),
                status="failed",
                verified_at=_utc_now(),
                detail=str(exc)[:500],
            ),
            ok=False,
        )
    except Exception as exc:  # noqa: BLE001 — surface to caller as failed offsite
        logger.exception("offsite %s failed", sink_type)
        return OffsiteResult(
            entry=OffsiteEntry(
                sink=sink_type,
                uri_or_label=_label_for(settings),
                status="failed",
                verified_at=_utc_now(),
                detail=str(exc)[:500],
            ),
            ok=False,
        )

    ok = entry.status == "ok"
    return OffsiteResult(entry=entry, ok=ok)


def _label_for(settings: OffsiteSinkSettings) -> str:
    if settings.type == "rsync":
        return settings.rsync_target
    if settings.hook_argv:
        return " ".join(shlex.quote(p) for p in settings.hook_argv[:4])
    return ""


def _run_hook(
    archive: Path,
    settings: OffsiteSinkSettings,
    *,
    integrity_path: Path | None,
    backup_id: str,
) -> OffsiteEntry:
    if not settings.hook_argv:
        raise OctopError(ErrorCode.SLASH_BAD_ARGS, "offsite hook_argv is empty")
    argv = _expand_argv(
        settings.hook_argv,
        archive=archive,
        integrity=integrity_path,
        backup_id=backup_id,
    )
    logger.info("offsite hook: %s", " ".join(shlex.quote(a) for a in argv))
    completed = subprocess.run(  # noqa: S603 — operator-configured argv
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or f"exit {completed.returncode}")[:500]
        raise OctopError(ErrorCode.INTERNAL_ERROR, f"offsite hook failed: {detail}")
    return OffsiteEntry(
        sink="hook",
        uri_or_label=_label_for(settings),
        status="ok",
        verified_at=_utc_now(),
        detail="hook exit 0",
    )


def _run_rsync(
    archive: Path,
    settings: OffsiteSinkSettings,
    *,
    integrity_path: Path | None,
) -> OffsiteEntry:
    target = (settings.rsync_target or "").strip()
    if not target:
        raise OctopError(ErrorCode.SLASH_BAD_ARGS, "offsite rsync_target is empty")
    sources = [str(archive)]
    if integrity_path is not None and integrity_path.is_file():
        sources.append(str(integrity_path))
    argv = ["rsync", "-av", "--chmod=Fu=rw,Fgo=", *settings.rsync_extra_args, *sources, target]
    logger.info("offsite rsync → %s", target)
    completed = subprocess.run(  # noqa: S603
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or f"exit {completed.returncode}")[:500]
        raise OctopError(ErrorCode.INTERNAL_ERROR, f"offsite rsync failed: {detail}")
    return OffsiteEntry(
        sink="rsync",
        uri_or_label=target,
        status="ok",
        verified_at=_utc_now(),
        detail="rsync exit 0",
    )


def offsite_settings_from_mapping(raw: dict[str, Any] | None) -> OffsiteSinkSettings:
    """Parse a nested ``backup.offsite`` object from config.json."""
    if not raw:
        return OffsiteSinkSettings()
    sink_type = str(raw.get("type", "hook")).strip().lower() or "hook"
    hook_raw = raw.get("hook_argv") or raw.get("hook") or []
    if isinstance(hook_raw, str):
        hook_argv = tuple(shlex.split(hook_raw))
    elif isinstance(hook_raw, list):
        hook_argv = tuple(str(x) for x in hook_raw)
    else:
        hook_argv = ()
    extra = raw.get("rsync_extra_args") or []
    extra_argv = tuple(str(x) for x in extra) if isinstance(extra, list) else ()
    return OffsiteSinkSettings(
        enabled=bool(raw.get("enabled", False)),
        type=sink_type,
        hook_argv=hook_argv,
        rsync_target=str(raw.get("rsync_target", "") or ""),
        rsync_extra_args=extra_argv,
    )
