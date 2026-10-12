"""Local device policy, confined file I/O and cancellable OS operations.

The server's grants can restrict the policy accepted at enrollment, never widen it.
An operation is durably recorded before its first side effect; interrupted operations
are not replayed after a restart.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import ctypes
import hashlib
import importlib.util
import json
import os
import platform
import shutil
import signal
import stat
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, cast

from octop.infra.devices.acp_process import DeviceACPProcesses

CHUNK_SIZE = 1024 * 1024
JOURNAL_LIMIT = 512
JOURNAL_BYTES_LIMIT = 8 * 1024 * 1024
OUTPUT_LIMIT = 1024 * 1024
CAPABILITIES = frozenset(
    {"desktop_view", "desktop_control", "files_read", "files_write", "command_exec", "acp_run"}
)


class DeviceExecutionError(ValueError):
    """A denied, invalid, unsupported or failed local operation."""


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
    )


def _reject_links(path: Path) -> None:
    for part in (path, *path.parents):
        if _is_link(part):
            raise DeviceExecutionError("symlink or reparse paths are not allowed")


def _bounded_command_result(result: dict[str, Any]) -> dict[str, Any]:
    """Budget the decoded output in the JSON encoding actually sent on the wire."""
    bounded = dict(result)
    truncated = bool(result.get("truncated", False))
    for key in ("stdout", "stderr"):
        value = result.get(key)
        if not isinstance(value, str):
            continue
        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) <= OUTPUT_LIMIT:
            continue
        low, high = 0, len(value)
        while low < high:
            middle = (low + high + 1) // 2
            if len(json.dumps(value[:middle], ensure_ascii=False).encode("utf-8")) <= OUTPUT_LIMIT:
                low = middle
            else:
                high = middle - 1
        bounded[key] = value[:low]
        truncated = True
    bounded["truncated"] = truncated
    return bounded


def _open_directory_nofollow(path: Path) -> int:
    """On POSIX, bind every directory component without traversing a symlink."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY") | getattr(os, "O_NOFOLLOW")  # noqa: B009 - POSIX constants are absent on Windows
    descriptor = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def private_state_dir(path: Path) -> Path:
    """Create device-only storage with a protected Windows ACL or POSIX mode."""
    path = path.absolute()
    _reject_links(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        path.chmod(0o700)
        return path
    # chmod on Windows does not protect credentials. Set a protected DACL that
    # grants the actual process identity (not an environment username) access.
    import csv
    from ctypes import wintypes

    identity = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"],
        check=True,
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    sid = next(csv.reader([identity.stdout.strip()]))[-1]
    if not sid.startswith("S-1-"):
        raise DeviceExecutionError("cannot protect device state")
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    descriptor = ctypes.c_void_p()
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
    ]
    advapi.GetSecurityDescriptorDacl.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.BOOL),
    ]
    advapi.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        f"D:P(A;OICI;FA;;;{sid})", 1, ctypes.byref(descriptor), None
    ):
        raise DeviceExecutionError("cannot protect device state")
    try:
        present, defaulted = wintypes.BOOL(), wintypes.BOOL()
        dacl = ctypes.c_void_p()
        if not advapi.GetSecurityDescriptorDacl(
            descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)
        ) or advapi.SetNamedSecurityInfoW(str(path), 1, 0x80000004, None, None, dacl, None):
            raise DeviceExecutionError("cannot protect device state")
    finally:
        kernel.LocalFree(descriptor)
    return path


def save_private_json(path: Path, data: dict[str, Any]) -> None:
    _reject_links(path)
    fd, temporary = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


@dataclass
class _Upload:
    root_id: str
    relative: str
    temporary: Path
    size: int
    sha256: str
    offset: int = 0


class _WindowsJob:
    """Contain a suspended child and kill its descendants when the job closes."""

    def __init__(self, pid: int) -> None:
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("per_process", ctypes.c_int64),
                ("per_job", ctypes.c_int64),
                ("flags", wintypes.DWORD),
                ("minimum", ctypes.c_size_t),
                ("maximum", ctypes.c_size_t),
                ("active", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("basic", BasicLimits),
                ("io", ctypes.c_uint64 * 6),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t),
                ("peak_job", ctypes.c_size_t),
            ]

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise DeviceExecutionError("cannot contain command process")
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        process = None
        try:
            if not self.kernel.SetInformationJobObject(
                self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            ):
                raise DeviceExecutionError("cannot contain command process")
            process = self.kernel.OpenProcess(0x0100 | 0x0001 | 0x0800, False, pid)
            if not process or not self.kernel.AssignProcessToJobObject(self.handle, process):
                raise DeviceExecutionError("cannot contain command process")
            # asyncio exposes the process but not its primary thread handle.
            # Resume only after assigning the still-suspended process to its job.
            ntdll = ctypes.WinDLL("ntdll")
            ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
            ntdll.NtResumeProcess.restype = ctypes.c_long
            if ntdll.NtResumeProcess(process) != 0:
                raise DeviceExecutionError("cannot start contained command")
        except BaseException:
            self.close()
            raise
        finally:
            if process:
                self.kernel.CloseHandle(process)

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class DeviceExecutor:
    def __init__(
        self,
        permissions: list[str],
        roots: list[dict[str, Any]],
        *,
        state_dir: Path | None = None,
        desktop_enabled: bool = False,
        control_enabled: bool = False,
        command_enabled: bool = False,
        acp_enabled: bool = False,
    ) -> None:
        if not set(permissions) <= CAPABILITIES:
            raise DeviceExecutionError("invalid local permissions")
        self.local_permissions = set(permissions)
        self.local_permissions -= {"desktop_view", "desktop_control", "command_exec", "acp_run"}
        if desktop_enabled:
            self.local_permissions.add("desktop_view")
        if control_enabled and desktop_enabled:
            self.local_permissions.add("desktop_control")
        if command_enabled:
            self.local_permissions.add("command_exec")
        if acp_enabled:
            self.local_permissions.add("acp_run")
        self.local_roots: dict[str, dict[str, Any]] = {}
        for root in roots:
            root_id = str(root["id"])
            if not root_id or root_id in self.local_roots:
                raise DeviceExecutionError("invalid shared root")
            path = Path(root["path"]).absolute()
            _reject_links(path)
            if not path.is_dir():
                raise DeviceExecutionError("shared root must be an existing directory")
            self.local_roots[root_id] = {
                "id": root_id,
                "name": str(root.get("name", root_id)),
                "path": str(path),
                "read": bool(root.get("read", False)),
                "write": bool(root.get("write", False)),
            }
        self.permissions = set(self.local_permissions)
        self.roots = dict(self.local_roots)
        self.grant_version = 0
        self._uploads: dict[str, _Upload] = {}
        self._active: dict[str, asyncio.Task[Any]] = {}
        self._capture: Any = None
        self._injector: Any = None
        self._acp: DeviceACPProcesses | None = None
        self.state_dir = private_state_dir(state_dir) if state_dir is not None else None
        self._journal: dict[str, Any] = {}
        if self.state_dir is not None:
            journal = self.state_dir / "operations.json"
            _reject_links(journal)
            if journal.exists():
                self._journal = json.loads(journal.read_text(encoding="utf-8"))
                for row in self._journal.values():
                    if row.get("state") == "running":
                        row.update(
                            state="unknown",
                            ok=False,
                            error="operation outcome unknown after restart",
                        )
                self._persist()
            manifest = self.state_dir / "uploads.json"
            _reject_links(manifest)
            if manifest.exists():
                for item in json.loads(manifest.read_text(encoding="utf-8")).values():
                    try:
                        target = self._path(item["root_id"], item["relative"], write=True)
                        name = item["temporary_name"]
                        if (
                            not isinstance(name, str)
                            or not name.startswith(".octop-upload-")
                            or Path(name).name != name
                        ):
                            continue
                        temporary = target.parent / name
                        _reject_links(temporary)
                        temporary.unlink(missing_ok=True)
                    except (OSError, DeviceExecutionError):
                        continue
                save_private_json(manifest, {})

    @property
    def capabilities(self) -> list[str]:
        result: set[str] = set()
        if any(root["read"] for root in self.local_roots.values()):
            result.add("files_read")
        if any(root["write"] for root in self.local_roots.values()):
            result.add("files_write")
        if "command_exec" in self.local_permissions:
            result.add("command_exec")
        if "acp_run" in self.local_permissions:
            result.add("acp_run")
        desktop_session = platform.system() == "Windows" or (
            platform.system() == "Linux"
            and bool(os.environ.get("DISPLAY"))
            and os.environ.get("XDG_SESSION_TYPE", "x11").lower() != "wayland"
        )
        if (
            desktop_session
            and "desktop_view" in self.local_permissions
            and (
                importlib.util.find_spec("mss") is not None
                or (platform.system() == "Linux" and shutil.which("import") is not None)
            )
        ):
            result.add("desktop_view")
            if "desktop_control" in self.local_permissions and importlib.util.find_spec("pynput"):
                result.add("desktop_control")
        return sorted(result)

    def update_grants(
        self, grant_version: int, permissions: list[str], roots: list[dict[str, Any]]
    ) -> None:
        if not isinstance(grant_version, int) or grant_version < self.grant_version:
            raise DeviceExecutionError("stale device grant")
        effective: dict[str, dict[str, Any]] = {}
        for remote in roots:
            local = self.local_roots.get(str(remote.get("id", "")))
            # No server-supplied path becomes a local root, even with the same id.
            if local is None or os.path.normcase(str(remote.get("path"))) != os.path.normcase(
                local["path"]
            ):
                continue
            effective[local["id"]] = {
                **local,
                "read": local["read"] and bool(remote.get("read")),
                "write": local["write"] and bool(remote.get("write")),
            }
        self.grant_version = grant_version
        self.permissions = self.local_permissions & set(permissions)
        self.roots = effective

    def _authorize(self, action: str, grant_version: int, permissions: list[str]) -> None:
        if grant_version != self.grant_version:
            raise DeviceExecutionError("stale device grant")
        required: set[str]
        if action in {"ping", "status"}:
            required = set()
        elif action in {"files.list", "files.stat", "files.read"}:
            required = {"files_read"}
        elif action.startswith("files.write_"):
            required = {"files_write"}
        elif action == "desktop.capture":
            required = {"desktop_view"}
        elif action == "desktop.input":
            required = {"desktop_view", "desktop_control"}
        elif action == "command.run":
            required = {"command_exec"}
        elif action.startswith("acp."):
            required = {"acp_run"}
        else:
            raise DeviceExecutionError("unsupported device action")
        if not required <= self.permissions & set(permissions):
            raise DeviceExecutionError("device permission denied")
        if not required <= set(self.capabilities):
            raise DeviceExecutionError("device capability unavailable")

    def _path(self, root_id: str, relative: str, *, write: bool = False) -> Path:
        root = self.roots.get(root_id)
        if root is None or not root["write" if write else "read"]:
            raise DeviceExecutionError("shared root permission denied")
        if not isinstance(relative, str) or "\x00" in relative:
            raise DeviceExecutionError("invalid relative path")
        normalized = relative.replace("\\", "/")
        windows = PureWindowsPath(relative)
        if (
            normalized.startswith("/")
            or windows.drive
            or ":" in normalized
            or any(part == ".." for part in normalized.split("/"))
        ):
            raise DeviceExecutionError("path must stay inside the shared root")
        base = Path(root["path"])
        path = base.joinpath(*normalized.split("/"))
        _reject_links(path)
        if not path.resolve().is_relative_to(base.resolve()):
            raise DeviceExecutionError("path must stay inside the shared root")
        return path

    def _persist(self) -> None:
        # Older journals may contain output that fit the raw read budget but
        # exceeds the JSON budget after escaping or UTF-8 replacement decoding.
        for row in self._journal.values():
            if row.get("action") == "command.run" and isinstance(row.get("result"), dict):
                row["result"] = _bounded_command_result(row["result"])
        while len(self._journal) > JOURNAL_LIMIT:
            candidate = next(
                (key for key, value in self._journal.items() if value["state"] != "running"), None
            )
            if candidate is None:
                break
            del self._journal[candidate]
        # Keep the operation-id tombstone when bulky read/command results
        # exceed the disk budget. Missing payloads require a new operation id.
        encoded = json.dumps(self._journal, ensure_ascii=False).encode("utf-8")
        if len(encoded) > JOURNAL_BYTES_LIMIT:
            for row in self._journal.values():
                result = row.get("result")
                if not isinstance(result, dict) or row.get("result_retained") is False:
                    continue
                row["result"] = {
                    key: result[key]
                    for key in (
                        "size",
                        "offset",
                        "eof",
                        "sha256",
                        "path",
                        "returncode",
                        "upload_id",
                        "bytes_done",
                    )
                    if key in result
                }
                row["result"]["payload_retained"] = False
                row["result_retained"] = False
                encoded = json.dumps(self._journal, ensure_ascii=False).encode("utf-8")
                if len(encoded) <= JOURNAL_BYTES_LIMIT:
                    break
        if self.state_dir is not None:
            save_private_json(self.state_dir / "operations.json", self._journal)

    def _persist_uploads(self) -> None:
        if self.state_dir is not None:
            save_private_json(
                self.state_dir / "uploads.json",
                {
                    key: {
                        "root_id": item.root_id,
                        "relative": item.relative,
                        "temporary_name": item.temporary.name,
                    }
                    for key, item in self._uploads.items()
                },
            )

    def reconciliation_results(self) -> list[dict[str, Any]]:
        return [
            {
                "id": key,
                "ok": row["ok"],
                **(
                    {
                        "result": _bounded_command_result(row["result"])
                        if row.get("action") == "command.run"
                        else row["result"]
                    }
                    if row["ok"]
                    else {"error": row["error"]}
                ),
            }
            for key, row in self._journal.items()
            if row["state"] != "running"
        ]

    async def execute(
        self,
        operation_id: str,
        action: str,
        params: dict[str, Any],
        *,
        grant_version: int,
        permissions: list[str],
    ) -> dict[str, Any]:
        self._authorize(action, grant_version, permissions)
        # ACP stdio is an ephemeral stream. Neither prompts nor output belong
        # in the durable operation journal or reconnect reconciliation.
        if action.startswith("acp."):
            try:
                return await self._execute(action, params)
            except ValueError as exc:
                raise DeviceExecutionError(str(exc)) from exc
            except OSError as exc:
                raise DeviceExecutionError("ACP process transport failed") from exc
        if not operation_id or len(operation_id) > 200:
            raise DeviceExecutionError("invalid operation id")
        fingerprint = hashlib.sha256(
            json.dumps([action, params], sort_keys=True).encode()
        ).hexdigest()
        existing = self._journal.get(operation_id)
        if existing is not None:
            if existing["fingerprint"] != fingerprint:
                raise DeviceExecutionError("operation id reused with different parameters")
            if existing["state"] == "running":
                raise DeviceExecutionError("operation already running")
            if not existing["ok"]:
                raise DeviceExecutionError(existing["error"])
            if existing.get("result_retained") is False:
                raise DeviceExecutionError("operation result not retained; request a new operation")
            if action == "command.run":
                return _bounded_command_result(existing["result"])
            return dict(existing["result"])
        current = asyncio.current_task()
        assert current is not None
        self._active[operation_id] = current
        self._journal[operation_id] = {
            "fingerprint": fingerprint,
            "state": "running",
            "action": action,
        }
        if action.startswith("files.write_") and "upload_id" in params:
            self._journal[operation_id]["upload_id"] = params["upload_id"]
        self._persist()
        before_uploads = set(self._uploads)
        try:
            result = await self._execute(action, params)
            receipt = result
            if action == "desktop.capture":
                receipt = {"captured": True, "width": result["width"], "height": result["height"]}
                self._journal[operation_id]["result_retained"] = False
            self._journal[operation_id].update(state="completed", ok=True, result=receipt)
            self._persist()
            return result
        except asyncio.CancelledError:
            self._journal[operation_id].update(
                state="cancelled", ok=False, error="operation cancelled"
            )
            self._persist()
            for upload_id in set(self._uploads) - before_uploads:
                self._abort(upload_id)
            raise
        except Exception as exc:
            message = (
                str(exc)
                if isinstance(exc, DeviceExecutionError)
                else "local device operation failed"
            )
            self._journal[operation_id].update(state="failed", ok=False, error=message)
            self._persist()
            raise DeviceExecutionError(message) from exc
        finally:
            self._active.pop(operation_id, None)

    @staticmethod
    def _number(
        params: dict[str, Any], key: str, default: int | None = None, *, maximum: int | None = None
    ) -> int:
        value = params.get(key, default)
        if type(value) is not int or value < 0 or (maximum is not None and value > maximum):
            raise DeviceExecutionError(f"invalid {key}")
        return value

    @staticmethod
    async def _sha256(path: Path | int) -> str:
        digest = hashlib.sha256()
        stream = os.fdopen(os.dup(path), "rb") if isinstance(path, int) else path.open("rb")
        with stream:
            stream.seek(0)
            for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
                digest.update(chunk)
                await asyncio.sleep(0)
        return digest.hexdigest()

    async def _commit_upload(self, upload: _Upload, destination: Path) -> str:
        root = Path(self.roots[upload.root_id]["path"])
        paths = (root, destination.parent, upload.temporary)
        for path in paths:
            _reject_links(path)
        snapshots = tuple(path.lstat() for path in paths)
        if not stat.S_ISREG(snapshots[2].st_mode):
            raise DeviceExecutionError("upload temporary file is not regular")
        parent_fd: int | None = None
        temporary_fd: int | None = None
        try:
            if os.name == "posix":
                parent_fd = _open_directory_nofollow(destination.parent)
                if not os.path.samestat(snapshots[1], os.fstat(parent_fd)):
                    raise DeviceExecutionError("upload directory changed")
                temporary_fd = os.open(
                    upload.temporary.name,
                    os.O_RDWR | getattr(os, "O_NOFOLLOW"),  # noqa: B009 - absent on Windows
                    dir_fd=parent_fd,
                )
                if not os.path.samestat(snapshots[2], os.fstat(temporary_fd)):
                    raise DeviceExecutionError("upload temporary file changed")
            digest = await self._sha256(
                temporary_fd if temporary_fd is not None else upload.temporary
            )
            # Hashing yields to the event loop. Recheck both directory identity
            # and links before any commit, including the Windows path fallback.
            self._path(upload.root_id, upload.relative, write=True)
            for path, before in zip(paths, snapshots, strict=True):
                _reject_links(path)
                if not os.path.samestat(before, path.lstat()):
                    raise DeviceExecutionError("upload path changed during checksum")
            after = upload.temporary.lstat()
            if (
                after.st_size != snapshots[2].st_size
                or after.st_mtime_ns != snapshots[2].st_mtime_ns
            ):
                raise DeviceExecutionError("upload contents changed during checksum")
            if (
                upload.offset != upload.size
                or after.st_size != upload.size
                or digest != upload.sha256
            ):
                raise DeviceExecutionError("upload size or checksum mismatch")
            if parent_fd is not None and temporary_fd is not None:
                os.fsync(temporary_fd)
                # Both names are interpreted in the directory we hashed in.
                # A replacement ancestor cannot redirect this atomic commit.
                os.link(
                    upload.temporary.name,
                    destination.name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                    follow_symlinks=False,
                )
                committed = os.stat(destination.name, dir_fd=parent_fd, follow_symlinks=False)
                if not os.path.samestat(os.fstat(temporary_fd), committed):
                    os.unlink(destination.name, dir_fd=parent_fd)
                    raise DeviceExecutionError("upload temporary file changed before commit")
                os.unlink(upload.temporary.name, dir_fd=parent_fd)
            else:
                # Windows has no Python dir_fd commit. These synchronous checks
                # reject changes across the await above; they are not an OS
                # directory-handle sandbox against concurrent local mutation.
                with upload.temporary.open("rb+") as stream:
                    if not os.path.samestat(snapshots[2], os.fstat(stream.fileno())):
                        raise DeviceExecutionError("upload temporary file changed before commit")
                    os.fsync(stream.fileno())
                os.link(upload.temporary, destination)
                if not os.path.samestat(snapshots[2], destination.lstat()):
                    destination.unlink()
                    raise DeviceExecutionError("upload temporary file changed before commit")
                upload.temporary.unlink()
            return digest
        except BaseException:
            if parent_fd is not None:
                # Even if the directory was renamed, remove our temporary name
                # in the bound directory rather than follow its replacement.
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(upload.temporary.name, dir_fd=parent_fd)
            raise
        finally:
            if temporary_fd is not None:
                os.close(temporary_fd)
            if parent_fd is not None:
                os.close(parent_fd)

    def _upload(self, params: dict[str, Any]) -> tuple[str, _Upload, Path]:
        upload_id = str(params.get("upload_id", ""))
        upload = self._uploads.get(upload_id)
        if upload is None:
            raise DeviceExecutionError("upload unavailable or interrupted")
        destination = self._path(upload.root_id, upload.relative, write=True)
        _reject_links(upload.temporary)
        return upload_id, upload, destination

    def _abort(self, upload_id: str) -> None:
        upload = self._uploads.pop(upload_id, None)
        if upload is not None:
            with contextlib.suppress(FileNotFoundError, DeviceExecutionError):
                _reject_links(upload.temporary)
                upload.temporary.unlink()
            self._persist_uploads()

    async def _execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action.startswith("acp."):
            if self._acp is None:
                self._acp = DeviceACPProcesses()
            session_id = str(params.get("session_id", ""))
            if action == "acp.open":
                root = self.roots.get(str(params.get("root_id", "")))
                if root is None or not root["read"] or not root["write"]:
                    raise DeviceExecutionError("ACP requires a writable shared root")
                return await self._acp.open(
                    cast(str, params.get("command")),
                    cast(list[str], params.get("args")),
                    Path(root["path"]),
                )
            if action == "acp.write":
                return await self._acp.write(session_id, cast(str, params.get("data_b64")))
            if action == "acp.poll":
                return await self._acp.poll(session_id)
            if action == "acp.close":
                return await self._acp.close(session_id)
            raise DeviceExecutionError("unsupported ACP action")
        if action in {"ping", "status"}:
            return {
                "platform": platform.system().lower(),
                "hostname": platform.node(),
                "capabilities": self.capabilities,
            }
        if action in {"files.list", "files.stat", "files.read", "files.write_begin"}:
            root_id = str(params.get("root_id", ""))
            relative = params.get("path", "")
            path = self._path(root_id, relative, write=action == "files.write_begin")
            if action == "files.list":
                entries = []
                for item in sorted(path.iterdir(), key=lambda entry: entry.name.casefold()):
                    # Links are neither followed nor advertised as accessible files.
                    if _is_link(item):
                        continue
                    entries.append(
                        {
                            "name": item.name,
                            "path": (Path(relative) / item.name).as_posix(),
                            "is_dir": item.is_dir(),
                            "size": item.stat().st_size,
                        }
                    )
                return {"entries": entries, "root_id": root_id, "path": relative}
            if action == "files.stat":
                is_dir = path.is_dir()
                return {
                    "size": path.stat().st_size,
                    "is_dir": is_dir,
                    **({} if is_dir else {"sha256": await self._sha256(path)}),
                }
            if action == "files.read":
                offset = self._number(params, "offset", 0)
                length = self._number(params, "length", CHUNK_SIZE, maximum=CHUNK_SIZE)
                size = path.stat().st_size
                if not path.is_file() or offset > size:
                    raise DeviceExecutionError("invalid file read")
                with path.open("rb") as stream:
                    stream.seek(offset)
                    data = stream.read(length)
                return {
                    "data_b64": base64.b64encode(data).decode("ascii"),
                    "size": size,
                    "offset": offset,
                    "eof": offset + len(data) >= size,
                }
            size = self._number(params, "size")
            expected = str(params.get("sha256", "")).lower()
            if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
                raise DeviceExecutionError("invalid sha256")
            if path.exists() or not path.parent.is_dir():
                raise DeviceExecutionError("destination exists or parent is unavailable")
            if len(self._uploads) >= 16:
                raise DeviceExecutionError("too many active uploads")
            upload_id = uuid.uuid4().hex
            temporary = path.parent / f".octop-upload-{uuid.uuid4().hex}"
            self._uploads[upload_id] = _Upload(root_id, relative, temporary, size, expected)
            self._persist_uploads()
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
            except BaseException:
                self._abort(upload_id)
                raise
            return {"upload_id": upload_id}
        if action.startswith("files.write_"):
            upload_id, upload, destination = self._upload(params)
            if action == "files.write_abort":
                self._abort(upload_id)
                return {"aborted": True}
            try:
                if action == "files.write_chunk":
                    offset = self._number(params, "offset")
                    encoded = params.get("data_b64")
                    if not isinstance(encoded, str) or len(encoded) > ((CHUNK_SIZE + 2) // 3) * 4:
                        raise DeviceExecutionError("invalid upload chunk")
                    try:
                        data = base64.b64decode(encoded, validate=True)
                    except (binascii.Error, ValueError) as exc:
                        raise DeviceExecutionError("invalid upload chunk") from exc
                    if (
                        offset != upload.offset
                        or len(data) > CHUNK_SIZE
                        or offset + len(data) > upload.size
                    ):
                        raise DeviceExecutionError("upload chunks must be ordered and bounded")
                    with upload.temporary.open("ab") as stream:
                        stream.write(data)
                    upload.offset += len(data)
                    return {"bytes_done": upload.offset}
                if action != "files.write_commit":
                    raise DeviceExecutionError("unsupported device action")
                digest = await self._commit_upload(upload, destination)
                del self._uploads[upload_id]
                self._persist_uploads()
                return {"size": upload.size, "sha256": digest, "path": upload.relative}
            except BaseException:
                self._abort(upload_id)
                raise
        if action == "desktop.capture":
            from octop.infra.desktop.capture import ScreenCapture

            quality = self._number(params, "quality", 80, maximum=100)
            if quality < 1:
                raise DeviceExecutionError("invalid quality")
            if self._capture is None:
                self._capture = ScreenCapture()
            # Keep the mss context and capture on the same thread.
            frame = self._capture.capture_jpeg(quality=quality)
            if frame is None:
                raise DeviceExecutionError("desktop capture unavailable")
            return {"jpeg_b64": frame.jpeg_b64, "width": frame.width, "height": frame.height}
        if action == "desktop.input":
            return self._input(params)
        if action == "command.run":
            return await self._command(params)
        raise DeviceExecutionError("unsupported device action")

    def _input(self, params: dict[str, Any]) -> dict[str, Any]:
        from octop.infra.desktop.input import InputInjector

        if self._injector is None:
            self._injector = InputInjector()
        kind = params.get("kind")
        if kind in {"click", "move", "scroll"}:
            x, y = self._number(params, "x"), self._number(params, "y")
            if kind == "click":
                button = params.get("button", "left")
                if button not in {"left", "right", "middle"}:
                    raise DeviceExecutionError("invalid mouse button")
                self._injector.click(x, y, button=button)
            elif kind == "move":
                self._injector.mouse_move(x, y)
            else:
                dy = params.get("dy", 0)
                if type(dy) not in {int, float} or abs(dy) > 10000:
                    raise DeviceExecutionError("invalid scroll delta")
                self._injector.scroll(x, y, delta_x=0, delta_y=dy)
        elif kind == "type":
            value = params.get("text")
            if not isinstance(value, str) or len(value) > 10000:
                raise DeviceExecutionError("invalid input text")
            self._injector.type_text(value)
        elif kind == "key":
            key = params.get("key")
            valid = {
                "Enter",
                "Backspace",
                "Tab",
                "Escape",
                "Delete",
                "ArrowUp",
                "ArrowDown",
                "ArrowLeft",
                "ArrowRight",
                "Home",
                "End",
                "PageUp",
                "PageDown",
                "Control",
                "Shift",
                "Alt",
                "Meta",
                *(f"F{i}" for i in range(1, 13)),
            }
            if not isinstance(key, str) or not (len(key) == 1 or key in valid):
                raise DeviceExecutionError("invalid input key")
            self._injector.key_down(key)
            self._injector.key_up(key)
        else:
            raise DeviceExecutionError("unsupported input kind")
        return {"ok": True}

    async def _command(self, params: dict[str, Any]) -> dict[str, Any]:
        argv = params.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or len(argv) > 256
            or any(
                not isinstance(value, str) or "\x00" in value or len(value) > 32768
                for value in argv
            )
            or not argv[0]
        ):
            raise DeviceExecutionError("argv must be a nonempty list of strings")
        timeout = self._number(params, "timeout", 60, maximum=3600)
        if timeout < 1:
            raise DeviceExecutionError("invalid timeout")
        root = self.roots.get(str(params.get("root_id", "")))
        if root is None:
            raise DeviceExecutionError("command root unavailable")
        # command_exec is a separate permission: read-only roots do not pretend
        # to sandbox commands that can write or access other OS resources.
        cwd = Path(root["path"])
        _reject_links(cwd)
        spawn: dict[str, Any] = {
            "cwd": cwd,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        if os.name == "nt":
            spawn["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW | 0x4
            )
        else:
            spawn["start_new_session"] = True
        launch = asyncio.create_task(asyncio.create_subprocess_exec(*argv, **spawn))
        try:
            process = await asyncio.shield(launch)
        except asyncio.CancelledError:
            # Shield the spawn handshake so cancellation cannot lose the only
            # process handle between CreateProcess/fork and the await result.
            process = await launch
            if os.name != "nt":
                with contextlib.suppress(ProcessLookupError):
                    getattr(os, "killpg")(process.pid, getattr(signal, "SIGKILL"))  # noqa: B009 - absent on Windows
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            raise
        job: _WindowsJob | None = None
        drains: list[asyncio.Task[tuple[bytes, bool]]] = []

        def stop_tree() -> None:
            if job is not None:
                job.close()
            elif os.name != "nt":
                with contextlib.suppress(ProcessLookupError):
                    getattr(os, "killpg")(process.pid, getattr(signal, "SIGKILL"))  # noqa: B009 - absent on Windows
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()

        async def drain(stream: asyncio.StreamReader | None) -> tuple[bytes, bool]:
            assert stream is not None
            data = bytearray()
            truncated = False
            while chunk := await stream.read(65536):
                remaining = OUTPUT_LIMIT - len(data)
                data.extend(chunk[:remaining])
                truncated |= len(chunk) > remaining
            return bytes(data), truncated

        async def parent_exit() -> None:
            # Process.wait() may also wait for inherited output pipes. Observe
            # the parent exit first, then stop descendants holding those pipes.
            while process.returncode is None:
                await asyncio.sleep(0.05)

        try:
            if os.name == "nt":
                job = _WindowsJob(process.pid)
            drains = [
                asyncio.create_task(drain(process.stdout)),
                asyncio.create_task(drain(process.stderr)),
            ]
            await asyncio.wait_for(parent_exit(), timeout)
            stop_tree()  # A normally exiting parent must not leave descendants.
            outputs = await asyncio.wait_for(asyncio.gather(*drains), 5)
            return _bounded_command_result(
                {
                    "returncode": process.returncode,
                    "stdout": outputs[0][0].decode("utf-8", "replace"),
                    "stderr": outputs[1][0].decode("utf-8", "replace"),
                    "truncated": outputs[0][1] or outputs[1][1],
                }
            )
        except TimeoutError as exc:
            raise DeviceExecutionError("command timed out") from exc
        finally:
            stop_tree()
            await process.wait()
            for task in drains:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*drains, return_exceptions=True)

    async def cancel(self, operation_id: str) -> None:
        task = self._active.get(operation_id)
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        receipt = self._journal.get(operation_id, {})
        upload_id = receipt.get("upload_id") or receipt.get("result", {}).get("upload_id")
        if isinstance(upload_id, str):
            self._abort(upload_id)

    def abort_uploads(self) -> None:
        for upload_id in list(self._uploads):
            self._abort(upload_id)

    async def close(self) -> None:
        if self._acp is not None:
            await self._acp.close_all()
        for operation_id in list(self._active):
            await self.cancel(operation_id)
        self.abort_uploads()
        if self._capture is not None:
            self._capture.close()
