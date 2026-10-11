"""Encrypted, offline relocation of one SQLite home to a fresh directory."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import sqlite3
import stat
import tarfile
import tempfile
from contextlib import closing
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import IO, Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from octop import __version__
from octop.i18n import tr
from octop.infra.agents.workspace.dir import workspace_dir_from_config_json
from octop.infra.backup.snapshot import snapshot_sqlite_file
from octop.infra.devices.executor import _reject_links, private_state_dir
from octop.infra.utils.paths import PathLayout
from octop.infra.utils.process_lock import ProcessLock

MAGIC = b"OCTOP-MOVE\x01"
CHUNK = 1024 * 1024
MAX_BYTES = 2 * 1024**3
MAX_FILES = 100000
_PATH_KEYS = {"workspace_dir", "root_dir", "sqlite_path", "cert_file", "key_file"}


class MigrationError(ValueError):
    """A failed move leaves the existing instance untouched."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(tr("migration.errors." + code))


def _key(password: str, salt: bytes) -> bytes:
    if len(password) < 12 or len(password) > 1024:
        raise MigrationError("password_length")
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600000).derive(
        password.encode("utf-8")
    )


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise MigrationError("invalid_json") from exc
    if not isinstance(value, dict):
        raise MigrationError("config_object")
    return value


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _absolute(path: Path) -> Path:
    path = path.expanduser().absolute()
    _reject_links(path)
    normalized = Path(os.path.abspath(path))
    _reject_links(normalized)
    return normalized


def _is_sqlite(path: Path) -> bool:
    with path.open("rb") as stream:
        return stream.read(16) == b"SQLite format 3\x00"


def _check_sqlite(path: Path) -> None:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise MigrationError("sqlite_integrity")


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master")}


def _source_database(home: Path, config: dict[str, Any]) -> Path:
    if any(value for key, value in os.environ.items() if key.startswith("OCTOP_DATABASE_")):
        raise MigrationError("database_environment")
    database = config.get("database", {})
    if not isinstance(database, dict) or database.get("driver", "sqlite") != "sqlite":
        raise MigrationError("sqlite_only")
    configured = Path(str(database.get("sqlite_path", "octop.db")))
    path = configured if configured.is_absolute() else home / configured
    path = _absolute(path)
    if not path.is_relative_to(home) or not path.is_file() or not _is_sqlite(path):
        raise MigrationError("database_inside")
    return path


def _check_idle(home: Path, database: Path) -> None:
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        tables = _tables(connection)
        if (
            "device_operations" in tables
            and connection.execute(
                "SELECT 1 FROM device_operations WHERE status IN ('queued','running') LIMIT 1"
            ).fetchone()
        ):
            raise MigrationError("active_device")
        if "task_boards" in tables:
            for (payload,) in connection.execute("SELECT payload FROM task_boards"):
                for task in json.loads(payload).get("tasks", []):
                    if any(run.get("state") == "running" for run in task.get("runs", [])):
                        raise MigrationError("active_task")
        if "agents" in tables:
            for agent_id, raw in connection.execute("SELECT agent_id, config_json FROM agents"):
                workspace = workspace_dir_from_config_json(
                    raw, paths=PathLayout(home), agent_id=agent_id, ensure=False
                )
                workspace = _absolute(workspace)
                if not workspace.is_relative_to(home):
                    raise MigrationError("external_workspace")


def _files(home: Path) -> list[Path]:
    result: list[Path] = []
    for directory, directories, files in os.walk(home, followlinks=False):
        parent = Path(directory)
        for name in [*directories, *files]:
            path = parent / name
            _reject_links(path)
            info = path.lstat()
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise MigrationError("special_source")
        result.extend(parent / name for name in files if parent / name != home / ".host.lock")
    sqlite_files = {path for path in result if _is_sqlite(path)}
    # Only exclude actual SQLite sidecars, never arbitrary similarly named documents.
    result = [
        path
        for path in result
        if not any(
            path == Path(str(db) + suffix) for db in sqlite_files for suffix in ("-wal", "-shm")
        )
    ]
    if len(result) > MAX_FILES or sum(path.stat().st_size for path in result) > MAX_BYTES:
        raise MigrationError("export_limit")
    return sorted(result)


def _encrypt(archive: Path, output: Path, password: str) -> None:
    salt, nonce = os.urandom(16), os.urandom(12)
    header = MAGIC + salt + nonce
    encryptor = Cipher(algorithms.AES(_key(password, salt)), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header)
    with archive.open("rb") as source, output.open("xb") as target:
        if os.name != "nt":
            output.chmod(0o600)
        target.write(header)
        while data := source.read(CHUNK):
            target.write(encryptor.update(data))
        target.write(encryptor.finalize())
        target.write(encryptor.tag)
        target.flush()
        os.fsync(target.fileno())


def _decrypt(source: Path, archive: Path, password: str) -> None:
    size = source.stat().st_size
    header_size = len(MAGIC) + 28
    if not header_size + 16 < size <= MAX_BYTES + CHUNK:
        raise MigrationError("encrypted_size")
    with source.open("rb") as stream:
        header = stream.read(header_size)
        if not header.startswith(MAGIC):
            raise MigrationError("format_version")
        stream.seek(-16, os.SEEK_END)
        tag = stream.read(16)
        salt, nonce = header[len(MAGIC) : len(MAGIC) + 16], header[-12:]
        decryptor = Cipher(algorithms.AES(_key(password, salt)), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(header)
        stream.seek(header_size)
        remaining = size - header_size - 16
        try:
            with archive.open("xb") as target:
                while remaining:
                    data = stream.read(min(CHUNK, remaining))
                    if not data:
                        raise MigrationError("cipher_truncated")
                    remaining -= len(data)
                    target.write(decryptor.update(data))
                target.write(decryptor.finalize())
        except InvalidTag as exc:
            raise MigrationError("authentication") from exc


def create_migration_archive(home: Path, output: Path, password: str) -> dict[str, Any]:
    """Require a stopped manager and leave its data unchanged."""
    home, output = _absolute(home), _absolute(output)
    if output.exists() or output.is_relative_to(home):
        raise MigrationError("output_fresh")
    _key(password, b"\0" * 16)  # Validate before opening source files.
    with ProcessLock(home / ".host.lock"):
        config = _json(home / "config.json")
        database = _source_database(home, config)
        _check_idle(home, database)
        files = _files(home)
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="octop-move-", dir=output.parent) as temporary:
            staging = private_state_dir(Path(temporary))
            data_root = staging / "home"
            data_root.mkdir()
            manifest: dict[str, Any] = {
                "version": 1,
                "platform": platform.system(),
                "octop_version": __version__,
                "source_home": str(home),
                "database": database.relative_to(home).as_posix(),
                "files": {},
            }
            for source in files:
                relative = source.relative_to(home).as_posix()
                _safe_name("home/" + relative)
                dest = data_root / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                if _is_sqlite(source):
                    snapshot_sqlite_file(source, dest)
                    _check_sqlite(dest)
                else:
                    with source.open("rb") as reader, dest.open("xb") as writer:
                        _copy(reader, writer, source.stat().st_size)
                manifest["files"][relative] = {"size": dest.stat().st_size, "sha256": _digest(dest)}
            manifest_path = staging / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            if (
                manifest_path.stat().st_size
                + sum(entry["size"] for entry in manifest["files"].values())
                > MAX_BYTES
            ):
                raise MigrationError("export_limit")
            archive, encrypted = staging / "home.tar.gz", staging / "encrypted"
            with tarfile.open(archive, "w:gz") as bundle:
                bundle.add(manifest_path, arcname="manifest.json", recursive=False)
                for relative in manifest["files"]:
                    bundle.add(data_root / relative, arcname="home/" + relative, recursive=False)
            _encrypt(archive, encrypted, password)
            # link publishes without replacing an existing output, including a concurrent one.
            os.link(encrypted, output)
    return {"output": str(output), "files": len(files), "sha256": _digest(output)}


def _safe_name(name: str) -> str:
    path = PurePosixPath(name)
    if (
        name != path.as_posix()
        or path.is_absolute()
        or any(
            part in {".", ".."}
            or any(char in part for char in '\\:<>"|?*')
            or any(ord(char) < 32 for char in part)
            for part in path.parts
        )
        or not path.parts
        or path.parts[0] not in {"home", "manifest.json"}
        or name.startswith("manifest.json/")
    ):
        raise MigrationError("unsafe_member")
    # Reject Windows device names and aliases, even on a POSIX producer.
    for part in path.parts:
        stem = part.partition(".")[0].upper()
        if part.endswith((".", " ")) or stem in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }:
            raise MigrationError("filename")
    return name


def _copy(source: IO[bytes], target: IO[bytes], size: int) -> None:
    remaining = size
    while remaining:
        data = source.read(min(CHUNK, remaining))
        if not data:
            raise MigrationError("file_truncated")
        remaining -= len(data)
        target.write(data)


def _extract(archive: Path, staging: Path) -> dict[str, Any]:
    seen: set[str] = set()
    aliases: set[str] = set()
    total = 0
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle:
            name = _safe_name(member.name)
            alias = name.casefold() if os.name == "nt" else name
            if alias in aliases or not member.isfile() or name == "home":
                raise MigrationError("member_type")
            seen.add(name)
            aliases.add(alias)
            total += member.size
            if (
                member.size < 0
                or total > MAX_BYTES
                or len(seen) > MAX_FILES + 1
                or name == "manifest.json"
                and member.size > 32 * CHUNK
            ):
                raise MigrationError("extract_limit")
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            reader = bundle.extractfile(member)
            if reader is None:
                raise MigrationError("invalid_member")
            with reader, path.open("xb") as writer:
                _copy(reader, writer, member.size)
    manifest = _json(staging / "manifest.json")
    files = manifest.get("files")
    if (
        manifest.get("version") != 1
        or manifest.get("platform") != platform.system()
        or not isinstance(manifest.get("source_home"), str)
        or not isinstance(files, dict)
        or not files
        or not all(isinstance(name, str) for name in files)
        or {"home/" + name for name in files} | {"manifest.json"} != seen
    ):
        raise MigrationError("manifest")
    if not Path(manifest["source_home"]).is_absolute():
        raise MigrationError("source_home")
    for relative, entry in files.items():
        path = staging / _safe_name("home/" + relative)
        if (
            not isinstance(entry, dict)
            or entry.get("size") != path.stat().st_size
            or entry.get("sha256") != _digest(path)
        ):
            raise MigrationError("checksum")
        if _is_sqlite(path):
            _check_sqlite(path.absolute())
    return manifest


def _remap(value: Any, old: str, target: Path) -> Any:
    if isinstance(value, list):
        return [_remap(item, old, target) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    old_path = PureWindowsPath(old) if platform.system() == "Windows" else PurePosixPath(old)
    for key, item in value.items():
        if key in _PATH_KEYS and isinstance(item, str):
            path = type(old_path)(os.path.normpath(item))
            if path.is_absolute() and path.is_relative_to(old_path):
                item = str(target.joinpath(*path.relative_to(old_path).parts))
        result[key] = _remap(item, old, target)
    return result


def _publish_home(source: Path, target: Path) -> None:
    """A competing creator must not lose even an empty destination directory."""
    if os.name == "nt":
        source.rename(target)  # Windows rename never replaces an existing directory.
    elif platform.system() == "Linux":
        rename = ctypes.CDLL(None, use_errno=True).renameat2
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
    else:
        raise MigrationError("platform")


def restore_migration_archive(source: Path, target: Path, password: str) -> dict[str, Any]:
    """Authenticate, validate, rebase and publish into an absent home only."""
    source, target = _absolute(source), _absolute(target)
    if target.exists():
        raise MigrationError("target_exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="octop-move-", dir=target.parent) as temporary:
        staging = private_state_dir(Path(temporary))
        archive, extracted = staging / "home.tar.gz", staging / "extracted"
        _decrypt(source, archive, password)
        try:
            manifest = _extract(archive, extracted)
        except tarfile.TarError as exc:
            raise MigrationError("invalid_archive") from exc
        data_root = extracted / "home"
        config = _remap(_json(data_root / "config.json"), manifest["source_home"], target)
        # Open the staged DB using its archived relative path, not the future configured path.
        db_relative = manifest.get("database")
        if not isinstance(db_relative, str) or db_relative not in manifest["files"]:
            raise MigrationError("database_manifest")
        database = data_root / db_relative
        if not _is_sqlite(database):
            raise MigrationError("database_format")
        rebased = 0
        with closing(sqlite3.connect(database)) as connection, connection:
            for table in ("agents", "storage_backends"):
                if table not in _tables(connection):
                    continue
                for pk, raw in connection.execute(f'SELECT id, config_json FROM "{table}"'):
                    if raw is None:
                        continue
                    original = json.loads(raw)
                    updated = _remap(original, manifest["source_home"], target)
                    if updated != original:
                        connection.execute(
                            f'UPDATE "{table}" SET config_json = ? WHERE id = ?',
                            (json.dumps(updated, ensure_ascii=False), pk),
                        )
                        rebased += 1
        _check_sqlite(database.absolute())
        (data_root / "config.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # The home inherits the current user's protected staging ACL; retain it after rename.
        private_state_dir(data_root)
        if target.exists():
            raise MigrationError("target_race")
        _publish_home(data_root, target)
    return {"home": str(target), "files": len(manifest["files"]), "rebased_records": rebased}
