"""Automatic system backup scheduling (process-level CronManager job)."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from octop.config import BackupConfig, BackupOffsiteConfig, OctopConfig, load_config
from octop.infra.backup.alerts import AlertSettings, check_disk_and_alert, emit_alert
from octop.infra.backup.integrity import (
    build_integrity_for_archive,
    integrity_sidecar_path,
    save_integrity_for_archive,
)
from octop.infra.backup.offsite import OffsiteSinkSettings, run_offsite
from octop.infra.backup.store import (
    BackupFileInfo,
    is_auto_backup_filename,
    place_backup_file,
    prune_auto_backups,
    resolve_backup_path,
)
from octop.infra.backup.system_archive import create_system_backup
from octop.infra.backup.verify import verify_backup_archive
from octop.infra.cron.trigger import build_trigger
from octop.infra.db.repos.audit import ACTOR_SYSTEM
from octop.infra.errors import ErrorCode, OctopError

if TYPE_CHECKING:
    from octop.config import DatabaseConfig
    from octop.infra.cron.manager import CronManager
    from octop.infra.db.pool import DatabasePool
    from octop.infra.server import OctopServer
    from octop.infra.utils.paths import PathLayout

logger = logging.getLogger(__name__)

AUTO_BACKUP_JOB_ID = "octop_auto_backup"
_AUTO_FILENAME_PREFIX = "octop-auto-backup-"
_MANUAL_FILENAME_PREFIX = "octop-backup-"

BackupOperation = Literal["create", "restore", "auto", "export"]

_lock = asyncio.Lock()
_active_operation: BackupOperation | None = None

# Shared with manual create so concurrent backups do not overlap.
BACKUP_LOCK = _lock


def get_backup_operation() -> BackupOperation | None:
    """Return the in-flight backup/restore kind, or ``None`` when idle."""
    if not _lock.locked():
        return None
    return _active_operation


def backup_status_payload() -> dict[str, Any]:
    op = get_backup_operation()
    return {"busy": op is not None, "operation": op}


@asynccontextmanager
async def hold_backup_lock(operation: BackupOperation) -> AsyncIterator[None]:
    """Acquire ``BACKUP_LOCK`` and publish *operation* for status polling."""
    global _active_operation
    async with _lock:
        _active_operation = operation
        try:
            yield
        finally:
            _active_operation = None


def raise_if_backup_busy() -> None:
    if _lock.locked():
        raise OctopError(
            ErrorCode.BACKUP_IN_PROGRESS,
            "a backup or restore is already in progress",
        )


def to_auto_backup_filename(suggested: str) -> str:
    """Map ``octop-backup-*.tar.gz`` → ``octop-auto-backup-*.tar.gz``."""
    name = Path(suggested).name
    if is_auto_backup_filename(name):
        return name
    if name.startswith(_MANUAL_FILENAME_PREFIX):
        return _AUTO_FILENAME_PREFIX + name.removeprefix(_MANUAL_FILENAME_PREFIX)
    raise OctopError(ErrorCode.SLASH_BAD_ARGS, f"unexpected backup filename: {name!r}")


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def persist_backup_config(config_path: Path, backup: BackupConfig) -> OctopConfig:
    """Merge ``backup`` into ``config.json`` and return the reloaded config."""
    if config_path.exists():
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise OctopError(ErrorCode.INTERNAL_ERROR, "config.json must be a JSON object")
    else:
        raw = {}

    raw["backup"] = {
        "auto_enabled": backup.auto_enabled,
        "schedule": backup.schedule,
        "retention_count": backup.retention_count,
        "include_config": backup.include_config,
        "include_workspaces": backup.include_workspaces,
        "include_skill_packages": backup.include_skill_packages,
        "include_plugins": backup.include_plugins,
        "include_knowledge": backup.include_knowledge,
        "include_chats": backup.include_chats,
        "alert_webhook_url": backup.alert_webhook_url,
        "disk_free_percent_min": backup.disk_free_percent_min,
        "offsite": {
            "enabled": backup.offsite.enabled,
            "type": backup.offsite.type,
            "hook_argv": list(backup.offsite.hook_argv),
            "rsync_target": backup.offsite.rsync_target,
            "rsync_extra_args": list(backup.offsite.rsync_extra_args),
        },
    }
    _atomic_write_json(config_path, raw)
    return load_config(config_path)


def backup_config_from_payload(
    payload: dict[str, Any],
    *,
    defaults: BackupConfig | None = None,
) -> BackupConfig:
    """Validate an API/CLI payload into ``BackupConfig``.

    When *defaults* is provided (e.g. current on-disk backup config), missing
    offsite/alert fields are preserved instead of resetting to empty factory
    defaults. ``PUT /backup/auto`` only sends schedule/include fields, so it
    must pass the existing config here (0026 Medium).
    """
    defaults = defaults if defaults is not None else BackupConfig()
    schedule = str(payload.get("schedule", defaults.schedule)).strip() or defaults.schedule
    try:
        build_trigger(schedule)
    except OctopError as exc:
        raise OctopError(ErrorCode.SLASH_BAD_ARGS, f"invalid backup schedule: {schedule}") from exc
    try:
        retention = int(payload.get("retention_count", defaults.retention_count))
    except (TypeError, ValueError) as exc:
        raise OctopError(ErrorCode.SLASH_BAD_ARGS, "retention_count must be an integer") from exc
    if retention < 1:
        raise OctopError(ErrorCode.SLASH_BAD_ARGS, "retention_count must be >= 1")
    offsite_raw = payload.get("offsite")
    if isinstance(offsite_raw, dict):
        offsite = BackupOffsiteConfig(
            enabled=bool(offsite_raw.get("enabled", defaults.offsite.enabled)),
            type=str(offsite_raw.get("type", defaults.offsite.type) or defaults.offsite.type),
            hook_argv=[
                str(x) for x in (offsite_raw.get("hook_argv") or defaults.offsite.hook_argv)
            ],
            rsync_target=str(offsite_raw.get("rsync_target", defaults.offsite.rsync_target) or ""),
            rsync_extra_args=[
                str(x)
                for x in (offsite_raw.get("rsync_extra_args") or defaults.offsite.rsync_extra_args)
            ],
        )
    else:
        offsite = defaults.offsite
    try:
        disk_min = float(payload.get("disk_free_percent_min", defaults.disk_free_percent_min))
    except (TypeError, ValueError) as exc:
        raise OctopError(
            ErrorCode.SLASH_BAD_ARGS, "disk_free_percent_min must be a number"
        ) from exc
    return BackupConfig(
        auto_enabled=bool(payload.get("auto_enabled", defaults.auto_enabled)),
        schedule=schedule,
        retention_count=retention,
        include_config=bool(payload.get("include_config", defaults.include_config)),
        include_workspaces=bool(payload.get("include_workspaces", defaults.include_workspaces)),
        include_skill_packages=bool(
            payload.get("include_skill_packages", defaults.include_skill_packages)
        ),
        include_plugins=bool(payload.get("include_plugins", defaults.include_plugins)),
        include_knowledge=bool(payload.get("include_knowledge", defaults.include_knowledge)),
        include_chats=bool(payload.get("include_chats", defaults.include_chats)),
        offsite=offsite,
        alert_webhook_url=str(payload.get("alert_webhook_url", defaults.alert_webhook_url) or ""),
        disk_free_percent_min=disk_min,
    )


def alert_settings_from_backup(backup: BackupConfig) -> AlertSettings:
    return AlertSettings(
        webhook_url=backup.alert_webhook_url,
        disk_free_percent_min=backup.disk_free_percent_min,
    )


def offsite_settings_from_backup(backup: BackupConfig) -> OffsiteSinkSettings:
    return OffsiteSinkSettings(
        enabled=backup.offsite.enabled,
        type=backup.offsite.type,
        hook_argv=tuple(backup.offsite.hook_argv),
        rsync_target=backup.offsite.rsync_target,
        rsync_extra_args=tuple(backup.offsite.rsync_extra_args),
    )


def finalize_backup_artifact(
    *,
    paths: PathLayout,
    entry: BackupFileInfo,
    backup: BackupConfig,
) -> dict[str, object]:
    """Write integrity sidecar, optional offsite, local verify (0026 S0).

    When offsite is enabled and fails, raises ``OctopError`` after alerting —
    overall backup must not be marked successful (DEC-B01 / AC-B02).
    """
    archive = resolve_backup_path(paths, entry.name)
    integrity = build_integrity_for_archive(archive, home=paths.root)
    sidecar = save_integrity_for_archive(integrity, archive)

    offsite_settings = offsite_settings_from_backup(backup)
    offsite_result = run_offsite(
        archive,
        offsite_settings,
        integrity_path=sidecar,
        backup_id=integrity.backup_id,
    )
    integrity.offsite = [offsite_result.entry]
    if not offsite_result.ok:
        integrity.verify_status = "failed"
        save_integrity_for_archive(integrity, archive)
        emit_alert(
            alert_settings_from_backup(backup),
            "offsite_failed",
            f"offsite failed for {entry.name}",
            detail={
                "backup": entry.name,
                "sink": offsite_result.entry.sink,
                "error": offsite_result.entry.detail,
            },
        )
        raise OctopError(
            ErrorCode.INTERNAL_ERROR,
            f"backup offsite failed: {offsite_result.entry.detail or offsite_result.entry.status}",
        )

    save_integrity_for_archive(integrity, archive)
    verified = verify_backup_archive(archive, update_sidecar=True)
    if not verified.ok:
        emit_alert(
            alert_settings_from_backup(backup),
            "backup_failed",
            f"backup verify failed for {entry.name}",
            detail={"backup": entry.name, "message": verified.message},
        )
        raise OctopError(ErrorCode.INTERNAL_ERROR, f"backup verify failed: {verified.message}")

    check_disk_and_alert(alert_settings_from_backup(backup), home=paths.root)
    return {
        "backup_id": integrity.backup_id,
        "integrity": str(integrity_sidecar_path(archive)),
        "offsite_status": offsite_result.entry.status,
        "verify_status": verified.verify_status,
        "sha256": verified.sha256,
    }


def create_and_store_auto_backup(
    *,
    paths: PathLayout,
    agent_rows: list[Any],
    pool: DatabasePool,
    db_config: DatabaseConfig,
    retention_count: int,
    include_config: bool = True,
    include_workspaces: bool = True,
    include_skill_packages: bool = True,
    include_plugins: bool = True,
    include_knowledge: bool = True,
    include_chats: bool = False,
) -> tuple[BackupFileInfo, list[str]]:
    """Create a selected-content system backup with the auto prefix and prune."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / "backup.tar.gz"
        suggested = create_system_backup(
            paths=paths,
            agent_rows=agent_rows,
            pool=pool,
            db_config=db_config,
            dest=tmp_path,
            include_config=include_config,
            include_workspaces=include_workspaces,
            include_skill_packages=include_skill_packages,
            include_plugins=include_plugins,
            include_knowledge=include_knowledge,
            include_chats=include_chats,
        )
        filename = to_auto_backup_filename(suggested)
        entry = place_backup_file(paths, filename, tmp_path)
    deleted = prune_auto_backups(paths, keep=retention_count)
    return entry, deleted


async def run_auto_backup(server: OctopServer) -> BackupFileInfo | None:
    """Run one automatic backup cycle. Returns ``None`` when skipped (busy/disabled)."""
    if _lock.locked():
        logger.info("auto backup skipped: another backup is already running")
        return None

    async with hold_backup_lock("auto"):
        config = load_config(server.paths.config)
        if server.services is None:
            logger.warning("auto backup skipped: server services not ready")
            return None

        retention = config.backup.retention_count
        try:
            if server.app_runtime is not None:
                agent_rows = cast(list[Any], server.app_runtime.agent_registry.list_rows())
            else:
                agent_rows = cast(list[Any], server.services.agent_repo.list_all())
            entry, deleted = await asyncio.to_thread(
                create_and_store_auto_backup,
                paths=server.paths,
                agent_rows=agent_rows,
                pool=server.services.db,
                db_config=server.services.config.database,
                retention_count=retention,
                include_config=config.backup.include_config,
                include_workspaces=config.backup.include_workspaces,
                include_skill_packages=config.backup.include_skill_packages,
                include_plugins=config.backup.include_plugins,
                include_knowledge=config.backup.include_knowledge,
                include_chats=config.backup.include_chats,
            )
        except Exception as exc:
            logger.exception("auto backup failed")
            try:
                emit_alert(
                    alert_settings_from_backup(config.backup),
                    "backup_failed",
                    "auto backup failed",
                    detail={"error": str(exc)[:500]},
                )
            except Exception:
                logger.exception("failed to emit backup_failed alert")
            try:
                server.services.audit_repo.write(
                    actor=ACTOR_SYSTEM,
                    action="backup.auto_failed",
                    target="",
                    payload=str(exc)[:500],
                )
            except Exception:
                logger.exception("failed to write backup.auto_failed audit")
            return None

        try:
            finalize_meta = finalize_backup_artifact(
                paths=server.paths,
                entry=entry,
                backup=config.backup,
            )
        except Exception as exc:
            logger.exception("auto backup finalize/offsite failed")
            try:
                emit_alert(
                    alert_settings_from_backup(config.backup),
                    "backup_failed",
                    "auto backup finalize failed",
                    detail={"backup": entry.name, "error": str(exc)[:500]},
                )
            except Exception:
                logger.exception("failed to emit finalize alert")
            try:
                server.services.audit_repo.write(
                    actor=ACTOR_SYSTEM,
                    action="backup.auto_failed",
                    target=entry.name,
                    payload=str(exc)[:500],
                )
            except Exception:
                logger.exception("failed to write backup.auto_failed audit")
            return None

        try:
            server.services.audit_repo.write(
                actor=ACTOR_SYSTEM,
                action="backup.auto_ok",
                target=entry.name,
                payload=json.dumps(
                    {"size": entry.size, "pruned": deleted, **finalize_meta},
                    default=str,
                ),
            )
        except Exception:
            logger.exception("failed to write backup.auto_ok audit")

        logger.info(
            "auto backup wrote %s (%d bytes); pruned %d; offsite=%s verify=%s",
            entry.name,
            entry.size,
            len(deleted),
            finalize_meta.get("offsite_status"),
            finalize_meta.get("verify_status"),
        )
        return entry


def apply_auto_backup_schedule(cron_manager: CronManager, *, server: OctopServer) -> None:
    """Register or remove the auto-backup system job from current config."""
    cron_manager.unschedule_system_job(AUTO_BACKUP_JOB_ID)
    config = load_config(server.paths.config)
    if not config.backup.auto_enabled:
        logger.info("auto backup disabled; system job not scheduled")
        return

    schedule = config.backup.schedule
    try:
        build_trigger(schedule)
    except OctopError:
        logger.warning("auto backup schedule %r is invalid; not scheduling", schedule)
        return

    async def _run() -> None:
        await run_auto_backup(server)

    cron_manager.schedule_system_job(
        AUTO_BACKUP_JOB_ID,
        trigger=schedule,
        func=_run,
    )
    logger.info("auto backup job scheduled (%s)", schedule)


def install_auto_backup_job(cron_manager: CronManager, *, server: OctopServer) -> None:
    """Boot-time hook: schedule auto backup when enabled in config."""
    apply_auto_backup_schedule(cron_manager, server=server)


def update_server_backup_config(server: OctopServer, backup: BackupConfig) -> OctopConfig:
    """Persist backup settings, refresh in-memory config, and reschedule the job."""
    new_config = persist_backup_config(server.paths.config, backup)
    server.config = new_config
    if server.services is not None:
        server.services = replace(server.services, config=new_config)
    if server.app_runtime is not None:
        apply_auto_backup_schedule(server.app_runtime.cron_manager, server=server)
    return new_config
