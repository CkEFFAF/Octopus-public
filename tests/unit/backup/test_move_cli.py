from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from octop.cli.commands import backup as commands
from octop.infra.backup.move import MigrationError
from octop.infra.utils.process_lock import ProcessAlreadyRunning


def test_export_password_is_hidden_and_passed_without_logging(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def export(home, archive, password):
        captured.update(home=home, password=password)
        return {"files": 3, "output": str(archive), "sha256": "test-digest"}

    monkeypatch.setattr(commands, "create_migration_archive", export)
    password = "a-secret-test-passphrase"
    result = CliRunner().invoke(
        commands.backup,
        ["move-export", "--home", str(tmp_path), "-o", str(tmp_path / "new.octopmove")],
        input=password + "\n" + password + "\n",
    )
    assert result.exit_code == 0, result.output
    assert captured["password"] == password
    assert password not in result.output
    assert "已导出 3 个文件" in result.output


def test_import_utf8_password_file_and_no_existing_data_initialization(
    monkeypatch, tmp_path: Path
) -> None:
    archive = tmp_path / "data.octopmove"
    archive.touch()
    key = tmp_path / "private.txt"
    key.write_text("\ufefftest-only-passphrase\r\n", encoding="utf-8")
    captured = {}

    def restore(source, target, password):
        captured.update(source=source, target=target, password=password)
        return {"home": str(target), "files": 5, "rebased_records": 1}

    monkeypatch.setattr(commands, "restore_migration_archive", restore)
    target = tmp_path / "new-home"
    result = CliRunner().invoke(
        commands.backup,
        [
            "move-import",
            str(archive),
            "--home",
            str(target),
            "--password-file",
            str(key),
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured == {"source": archive, "target": target, "password": "test-only-passphrase"}
    assert captured["password"] not in result.output
    assert not target.exists()
    assert "恢复未启动服务" in result.output


def test_domain_error_is_localized_without_disclosing_password(monkeypatch, tmp_path: Path) -> None:
    def export(*args):
        raise MigrationError("authentication")

    monkeypatch.setattr(commands, "create_migration_archive", export)
    key = tmp_path / "private.txt"
    key.write_text("private-test-passphrase")
    result = CliRunner().invoke(
        commands.backup,
        [
            "move-export",
            "--home",
            str(tmp_path),
            "-o",
            str(tmp_path / "new"),
            "--password-file",
            str(key),
        ],
    )
    assert result.exit_code == 1
    assert "迁移口令错误" in result.output
    assert "private-test-passphrase" not in result.output


def test_running_manager_error_is_actionable(monkeypatch, tmp_path: Path) -> None:
    def export(*args):
        raise ProcessAlreadyRunning

    monkeypatch.setattr(commands, "create_migration_archive", export)
    result = CliRunner().invoke(
        commands.backup,
        [
            "move-export",
            "--home",
            str(tmp_path),
            "-o",
            str(tmp_path / "new"),
            "--locale",
            "en",
        ],
        input="test-only-passphrase\ntest-only-passphrase\n",
    )
    assert result.exit_code == 1
    assert "Stop its manager" in result.output


def test_wizard_aborted_before_prompting_for_secret_or_domain_access(
    monkeypatch, tmp_path: Path
) -> None:
    def forbidden(*args):
        raise AssertionError("must not export")

    monkeypatch.setattr(commands, "create_migration_archive", forbidden)
    result = CliRunner().invoke(
        commands.backup, ["move"], input=f"1\n{tmp_path}\nnew.octopmove\nn\n"
    )
    assert result.exit_code == 1
    assert "迁移口令（" not in result.output


def test_password_file_size_limited_before_domain_access(tmp_path: Path) -> None:
    key = tmp_path / "private.txt"
    key.write_bytes(b"secret" * 1000)
    result = CliRunner().invoke(
        commands.backup,
        [
            "move-export",
            "--home",
            str(tmp_path),
            "-o",
            str(tmp_path / "new"),
            "--password-file",
            str(key),
        ],
    )
    assert result.exit_code == 1
    assert "最大 4 KiB" in result.output
    assert "secret" not in result.output
