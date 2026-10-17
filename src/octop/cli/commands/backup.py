"""`octop backup` — export and restore Octop data."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import click

from octop.config import load_config
from octop.i18n import tr
from octop.infra.backup.alerts import AlertSettings, check_disk_and_alert
from octop.infra.backup.auto import create_and_store_auto_backup, finalize_backup_artifact
from octop.infra.backup.move import (
    MigrationError,
    create_migration_archive,
    restore_migration_archive,
)
from octop.infra.backup.store import place_backup_file
from octop.infra.backup.system_archive import create_system_backup, restore_system_backup
from octop.infra.backup.verify import verify_backup_archive
from octop.infra.db.factory import open_database
from octop.infra.db.migrate import run_migrations
from octop.infra.db.services import build_shared_services
from octop.infra.utils.paths import PathLayout
from octop.infra.utils.process_lock import ProcessAlreadyRunning


def _paths(home: Path | None = None) -> PathLayout:
    return PathLayout(home) if home is not None else PathLayout.from_env()


@click.group()
def backup() -> None:
    """Backup and restore database + local agent workspaces."""


def _move_password(password_file: Path | None, *, exporting: bool, locale: str) -> str:
    if password_file is not None:
        try:
            with password_file.open("rb") as stream:
                data = stream.read(4097)
            if len(data) > 4096:
                raise ValueError
            return data.decode("utf-8-sig").rstrip("\r\n")
        except (OSError, ValueError):
            raise click.ClickException(tr("migration.password_file_error", locale)) from None
    return str(
        click.prompt(
            tr("migration.password", locale), hide_input=True, confirmation_prompt=exporting
        )
    )


def _move_run(
    home: Path, archive: Path, password_file: Path | None, *, exporting: bool, locale: str
) -> None:
    password = _move_password(password_file, exporting=exporting, locale=locale)
    try:
        report = (
            create_migration_archive(home, archive, password)
            if exporting
            else restore_migration_archive(archive, home, password)
        )
    except ProcessAlreadyRunning:
        raise click.ClickException(tr("migration.manager_running", locale)) from None
    except MigrationError as exc:
        raise click.ClickException(tr("migration.errors." + exc.code, locale)) from None
    except (OSError, ValueError, sqlite3.Error):
        raise click.ClickException(tr("migration.failed", locale)) from None
    click.echo(tr("migration.exported" if exporting else "migration.restored", locale, **report))
    click.echo(tr("migration.keep_separate" if exporting else "migration.restore_notes", locale))


@backup.command("move-export")
@click.option(
    "--home", type=click.Path(exists=True, file_okay=False, path_type=Path), required=True
)
@click.option("-o", "--output", type=click.Path(dir_okay=False, path_type=Path), required=True)
@click.option("--password-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--locale", type=click.Choice(["zh", "en"]), default="zh")
def move_export(home: Path, output: Path, password_file: Path | None, locale: str) -> None:
    """Encrypt a stopped manager's complete SQLite home for relocation."""
    _move_run(home, output, password_file, exporting=True, locale=locale)


@backup.command("move-import")
@click.argument("archive", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--home", type=click.Path(file_okay=False, path_type=Path), required=True)
@click.option("--password-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--locale", type=click.Choice(["zh", "en"]), default="zh")
def move_import(archive: Path, home: Path, password_file: Path | None, locale: str) -> None:
    """Restore the same instance into a NEW home; does not start services."""
    _move_run(home, archive, password_file, exporting=False, locale=locale)


@backup.command("move")
@click.option("--locale", type=click.Choice(["zh", "en"]), default="zh")
def move_wizard(locale: str) -> None:
    """Guided export/import with a hidden password prompt."""
    click.echo(tr("migration.intro", locale))
    action = click.prompt(tr("migration.action", locale), type=click.Choice(["1", "2"]))
    home = Path(click.prompt(tr("migration.home", locale), default=str(Path.cwd() / "data")))
    archive = Path(click.prompt(tr("migration.archive", locale)))
    click.echo(tr("migration.plan", locale, home=home, archive=archive))
    click.confirm(tr("migration.confirm", locale), abort=True)
    _move_run(home, archive, None, exporting=action == "1", locale=locale)


@backup.command("create")
@click.option(
    "-o", "--output", type=click.Path(path_type=Path), default=None, help="Output .tar.gz path."
)
@click.option(
    "--home", type=click.Path(path_type=Path), default=None, help="Octop home (default ~/.octop)."
)
@click.option("--no-config", is_flag=True, help="Do not include config.json / env.")
@click.option("--no-workspaces", is_flag=True, help="Do not include agent workspaces.")
@click.option("--no-skill-packages", is_flag=True, help="Do not include global skill packages.")
@click.option("--no-plugins", is_flag=True, help="Do not include installed plugins.")
@click.option("--no-knowledge", is_flag=True, help="Do not include knowledge base files.")
@click.option("--include-chats", is_flag=True, help="Include chat history (omitted by default).")
def create(
    output: Path | None,
    home: Path | None,
    no_config: bool,
    no_workspaces: bool,
    no_skill_packages: bool,
    no_plugins: bool,
    no_knowledge: bool,
    include_chats: bool,
) -> None:
    """Create a selected-content backup archive."""
    paths = _paths(home)
    config = load_config(paths.config)
    db = open_database(config, paths)
    run_migrations(db)
    services = build_shared_services(db=db, paths=paths, config=config)
    rows = services.agent_repo.list_all()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "backup.tar.gz"
            suggested = create_system_backup(
                paths=paths,
                agent_rows=rows,
                pool=db,
                db_config=config.database,
                dest=tmp_path,
                include_config=not no_config,
                include_workspaces=not no_workspaces,
                include_skill_packages=not no_skill_packages,
                include_plugins=not no_plugins,
                include_knowledge=not no_knowledge,
                include_chats=include_chats,
            )
            if output is None:
                entry = place_backup_file(paths, suggested, tmp_path)
                dest = paths.backup_file(entry.name)
                size = entry.size
                meta = finalize_backup_artifact(paths=paths, entry=entry, backup=config.backup)
            else:
                dest = output
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp_path.replace(dest)
                size = dest.stat().st_size
                meta = None
    finally:
        db.close()

    click.echo(f"wrote {dest} ({size} bytes)")
    if meta is not None:
        click.echo(
            f"integrity ok sha256={meta.get('sha256')} offsite={meta.get('offsite_status')} "
            f"verify={meta.get('verify_status')}"
        )


@backup.group("auto")
def auto() -> None:
    """Automatic backup status and one-shot run (schedule requires ``octop run``)."""


@auto.command("status")
@click.option(
    "--home", type=click.Path(path_type=Path), default=None, help="Octop home (default ~/.octop)."
)
def auto_status(home: Path | None) -> None:
    """Print automatic backup settings from config.json."""
    paths = _paths(home)
    config = load_config(paths.config)
    backup_cfg = config.backup
    click.echo(f"auto_enabled: {backup_cfg.auto_enabled}")
    click.echo(f"schedule: {backup_cfg.schedule}")
    click.echo(f"retention_count: {backup_cfg.retention_count}")
    click.echo(f"include_config: {backup_cfg.include_config}")
    click.echo(f"include_workspaces: {backup_cfg.include_workspaces}")
    click.echo(f"include_skill_packages: {backup_cfg.include_skill_packages}")
    click.echo(f"include_plugins: {backup_cfg.include_plugins}")
    click.echo(f"include_knowledge: {backup_cfg.include_knowledge}")
    click.echo(f"include_chats: {backup_cfg.include_chats}")
    click.echo("note: the scheduler only runs inside an active `octop run` process")


@auto.command("run")
@click.option(
    "--home", type=click.Path(path_type=Path), default=None, help="Octop home (default ~/.octop)."
)
def auto_run(home: Path | None) -> None:
    """Create one automatic backup now and apply retention pruning."""
    paths = _paths(home)
    config = load_config(paths.config)
    db = open_database(config, paths)
    run_migrations(db)
    services = build_shared_services(db=db, paths=paths, config=config)
    rows = services.agent_repo.list_all()
    try:
        entry, deleted = create_and_store_auto_backup(
            paths=paths,
            agent_rows=rows,
            pool=db,
            db_config=config.database,
            retention_count=config.backup.retention_count,
            include_config=config.backup.include_config,
            include_workspaces=config.backup.include_workspaces,
            include_skill_packages=config.backup.include_skill_packages,
            include_plugins=config.backup.include_plugins,
            include_knowledge=config.backup.include_knowledge,
            include_chats=config.backup.include_chats,
        )
        meta = finalize_backup_artifact(paths=paths, entry=entry, backup=config.backup)
    finally:
        db.close()
    click.echo(f"wrote {paths.backup_file(entry.name)} ({entry.size} bytes)")
    click.echo(
        f"integrity ok sha256={meta.get('sha256')} offsite={meta.get('offsite_status')} "
        f"verify={meta.get('verify_status')}"
    )
    if deleted:
        click.echo(f"pruned: {', '.join(deleted)}")


@backup.command("restore")
@click.argument("archive", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--home", type=click.Path(path_type=Path), default=None, help="Octop home (default ~/.octop)."
)
@click.option("--no-config", is_flag=True, default=False, help="Do not restore config.json / env.")
@click.option(
    "--owner-user-id",
    type=int,
    default=None,
    help="For LightClaw migration archives: Octop user id that receives imported ownership "
    "(default: first admin among current users).",
)
@click.option("--yes", is_flag=True, default=False, help="Skip confirmation.")
def restore(
    archive: Path,
    home: Path | None,
    no_config: bool,
    owner_user_id: int | None,
    yes: bool,
) -> None:
    """Restore from a backup archive. Stop ``octop run`` first for a clean restore."""
    if not yes:
        click.confirm(
            "This overwrites the database and local workspaces. Continue?",
            abort=True,
        )
    paths = _paths(home)
    config = load_config(paths.config)
    db = open_database(config, paths)
    result = restore_system_backup(
        archive,
        paths=paths,
        pool=db,
        db_config=config.database,
        restore_config=not no_config,
        owner_user_id=owner_user_id,
    )
    db.close()
    click.echo(f"restored: {result}")


@backup.command("verify")
@click.argument("archive", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--no-update-sidecar", is_flag=True, help="Do not rewrite verify_status on the sidecar."
)
def verify_cmd(archive: Path, no_update_sidecar: bool) -> None:
    """Verify archive sha256 against the integrity sidecar and list tar members."""
    result = verify_backup_archive(archive, update_sidecar=not no_update_sidecar)
    click.echo(
        f"{'ok' if result.ok else 'FAILED'}: {result.message} "
        f"(members={result.member_count} sha256={result.sha256})"
    )
    if not result.ok:
        raise SystemExit(1)


@backup.command("health-check")
@click.option(
    "--home", type=click.Path(path_type=Path), default=None, help="Octop home (default OCTOP_HOME)."
)
def health_check_cmd(home: Path | None) -> None:
    """Disk free-space check (AC-B06 skeleton); alerts when below threshold."""
    paths = _paths(home)
    config = load_config(paths.config)
    settings = AlertSettings(
        webhook_url=config.backup.alert_webhook_url,
        disk_free_percent_min=config.backup.disk_free_percent_min,
    )
    from octop.infra.backup.alerts import disk_free_percent

    free_pct = disk_free_percent(paths.root)
    click.echo(
        f"disk_free_percent={free_pct:.2f} threshold={settings.disk_free_percent_min} home={paths.root}"
    )
    delivery = check_disk_and_alert(settings, home=paths.root)
    if delivery is None:
        click.echo("disk ok")
    else:
        click.echo(
            f"alert kind={delivery.kind} delivered={delivery.delivered} detail={delivery.detail}"
        )
        raise SystemExit(2)


@backup.command("drill")
@click.option("--dry-run", is_flag=True, default=True, help="Print runbook steps only (default).")
@click.option(
    "--home", type=click.Path(path_type=Path), default=None, help="Octop home for path hints."
)
def drill_cmd(dry_run: bool, home: Path | None) -> None:
    """Restore-drill helper. S0 is dry-run / runbook only (AC-B04)."""
    paths = _paths(home)
    click.echo("0026 restore drill (dry-run). Full runbook: docs/octopus/backup-restore-drill.md")
    click.echo(f"OCTOP_HOME hint: {paths.root}")
    steps = [
        "1. Pick a verified archive under $OCTOP_HOME/backups/ (octop backup verify <file>).",
        "2. Stop the hub service (systemctl stop octop-hub) — do not restore over a live writer.",
        "3. Restore into an *isolated* empty directory, e.g.:",
        "     mkdir -p /tmp/octop-drill && OCTOP_HOME=/tmp/octop-drill octop backup restore <archive> --yes",
        "4. Optionally start a throwaway process against that home and hit /api/health.",
        "5. Record RTO/RPO and outcome in audit / ops notes; destroy the drill home.",
        "6. Quarterly: empty OctopData + install-hub / upgrade path per 0027 runbook.",
    ]
    for line in steps:
        click.echo(line)
    if dry_run:
        click.echo("dry-run complete (no restore executed).")
