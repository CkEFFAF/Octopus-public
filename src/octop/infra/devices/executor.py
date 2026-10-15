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
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING, Any, cast

from octop.infra.devices.acp_process import DeviceACPProcesses
from octop.infra.devices.process_scope import ProcessScopeError, WindowsJob

if TYPE_CHECKING:
    from octop.infra.devices.browser import DeviceBrowsers
    from octop.infra.devices.desktop import DeviceDesktop
    from octop.infra.devices.terminal import DeviceTerminals
    from octop.infra.devices.transfers import NativeTransfers

CHUNK_SIZE = 1024 * 1024
JOURNAL_LIMIT = 512
JOURNAL_BYTES_LIMIT = 8 * 1024 * 1024
OUTPUT_LIMIT = 1024 * 1024
CAPABILITIES = frozenset(
    {"desktop_view", "desktop_control", "files_read", "files_write", "command_exec", "acp_run"}
)


def _registry_text(path: str, name: str) -> str:
    with contextlib.suppress(Exception):
        registry = importlib.import_module("winreg")
        with registry.OpenKey(registry.HKEY_LOCAL_MACHINE, path) as key:
            value, _ = registry.QueryValueEx(key, name)
        if isinstance(value, str):
            return value.strip()[:200]
    return ""


def _system_file_text(path: Path) -> str:
    with contextlib.suppress(OSError):
        return path.read_text(encoding="utf-8").strip()[:100]
    return ""


def _system_details() -> dict[str, str]:
    """Small on-demand system snapshot without secrets or process data."""
    system = platform.system()
    details = {
        "os_version": platform.platform(aliased=True, terse=True)[:200],
        "architecture": platform.machine()[:80],
    }
    cpu = platform.processor().strip()
    board = ""
    if system == "Windows":
        cpu = (
            _registry_text(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString")
            or cpu
        )
        bios = r"HARDWARE\DESCRIPTION\System\BIOS"
        board = " ".join(
            part
            for part in (
                _registry_text(bios, "BaseBoardManufacturer"),
                _registry_text(bios, "BaseBoardProduct"),
            )
            if part
        )
    elif system == "Linux":
        with contextlib.suppress(OSError):
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
                if line.startswith(("model name\t:", "Hardware\t:")):
                    cpu = line.partition(":")[2].strip()
                    break
        board = " ".join(
            part
            for path in (
                Path("/sys/devices/virtual/dmi/id/board_vendor"),
                Path("/sys/devices/virtual/dmi/id/board_name"),
            )
            if (part := _system_file_text(path))
        )
        with contextlib.suppress(OSError):
            details["os_version"] = platform.freedesktop_os_release().get(
                "PRETTY_NAME", details["os_version"]
            )[:200]
    if cpu:
        details["cpu"] = cpu[:200]
    if board:
        details["mainboard"] = board[:200]
    return details


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
        creationflags=subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined, unused-ignore]
    )
    sid = next(csv.reader([identity.stdout.strip()]))[-1]
    if not sid.startswith("S-1-"):
        raise DeviceExecutionError("cannot protect device state")
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined, unused-ignore]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined, unused-ignore]
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
    from octop.infra.devices.state_io import retry_file_lock

    _reject_links(path)
    fd, temporary = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        retry_file_lock(lambda: os.replace(temporary, path))
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
        trust_mode: str = "restricted",
        working_dir: str | None = None,
    ) -> None:
        if trust_mode not in {"owner", "restricted"} or not set(permissions) <= CAPABILITIES:
            raise DeviceExecutionError("invalid local permissions")
        self._policy_lock = threading.RLock()
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
            if trust_mode != "owner":
                _reject_links(path)
            if trust_mode != "owner" and not path.is_dir():
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
        self.trust_mode = "restricted"
        self.working_dir = Path(
            working_dir or (roots[0]["path"] if roots else Path.home())
        ).resolve()
        if trust_mode == "owner":
            # A saved default directory may have been renamed while offline.
            # Identity and connectivity must survive so policy can be repaired.
            self.trust_mode = trust_mode
            self.local_permissions = set(permissions) & set(self.capabilities)
            self.permissions = set(self.local_permissions)
        self._uploads: dict[str, _Upload] = {}
        self._active: dict[str, asyncio.Task[Any]] = {}
        self._desktop: DeviceDesktop | None = None
        self._acp: DeviceACPProcesses | None = None
        self._terminals: DeviceTerminals | None = None
        self._browsers: DeviceBrowsers | None = None
        self._transfers: NativeTransfers | None = None
        self._transfer_reaper: asyncio.Task[None] | None = None
        self.state_dir = private_state_dir(state_dir) if state_dir is not None else None
        from octop.infra.devices.jobs import JobSupervisor

        self._job_supervisor = JobSupervisor(self.state_dir / "jobs") if self.state_dir else None
        self._private_paths: list[Path] = []
        if self.state_dir is not None:
            state_root = self.state_dir
            if state_root.parent.name == "controllers":
                state_root = state_root.parent.parent
            self._private_paths.append(state_root.resolve())
        # Remote file writes must not replace the running consent implementation.
        package_root = Path(__file__).resolve().parents[2]
        runtime_root = package_root.parent
        if runtime_root.name == "packages" and (runtime_root.parent / "launch.py").is_file():
            runtime_root = runtime_root.parent
        self._private_paths.append(runtime_root)
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
        """Hardware/client support ceiling (0005): not limited to current consent."""
        result: set[str] = {"files_read", "files_write", "command_exec", "acp_run"}
        desktop_session = platform.system() == "Windows" or (
            platform.system() == "Linux"
            and bool(os.environ.get("DISPLAY"))
            and os.environ.get("XDG_SESSION_TYPE", "x11").lower() != "wayland"
        )
        if desktop_session and (
            importlib.util.find_spec("mss") is not None
            or (platform.system() == "Linux" and shutil.which("import") is not None)
        ):
            result.add("desktop_view")
            if importlib.util.find_spec("pynput"):
                result.add("desktop_control")
        return sorted(result)

    def root_candidates(self) -> list[dict[str, Any]]:
        """Existing shared directories the control center may select (no mkdir)."""
        return [
            {
                "id": root["id"],
                "name": root["name"],
                "path": root["path"],
                "read": root["read"],
                "write": root["write"],
            }
            for root in self.local_roots.values()
        ]

    def apply_policy(
        self, trust_mode: str, permissions: list[str], working_dir: str | None
    ) -> None:
        if trust_mode not in {"owner", "restricted"} or not set(permissions) <= CAPABILITIES:
            raise DeviceExecutionError("invalid device policy")
        directory = Path(working_dir).expanduser() if working_dir else self.working_dir
        if not directory.is_absolute() or not directory.is_dir():
            raise DeviceExecutionError("working directory must be an existing absolute directory")
        with self._policy_lock:
            if self._job_supervisor is not None and (
                trust_mode != "owner" or "command_exec" not in permissions
            ):
                self._job_supervisor.cancel_active()
            self.working_dir = directory.resolve()
            self.trust_mode = trust_mode
            self.local_permissions = set(permissions) & set(self.capabilities)
            self.permissions = set(self.local_permissions)

    def command_directory(self, params: dict[str, Any]) -> Path:
        root = self.roots.get(str(params.get("root_id", "")))
        if self.trust_mode == "owner":
            raw = params.get("cwd") or (root["path"] if root is not None else str(self.working_dir))
            if not isinstance(raw, str):
                raise DeviceExecutionError("invalid command working directory")
            path = Path(raw).expanduser()
            if not path.is_absolute():
                path = self.working_dir / path
            if not path.is_dir():
                raise DeviceExecutionError("command working directory unavailable")
            return path.resolve()
        if root is None:
            raise DeviceExecutionError("command root unavailable")
        path = Path(root["path"])
        _reject_links(path)
        return path

    def stop_jobs(self) -> None:
        """Request cancellation after explicit revocation, not socket closure."""
        if self._job_supervisor is not None:
            self._job_supervisor.cancel_active()

    def update_grants(
        self, grant_version: int, permissions: list[str], roots: list[dict[str, Any]]
    ) -> None:
        if not isinstance(grant_version, int) or grant_version < self.grant_version:
            raise DeviceExecutionError("stale device grant")
        caps = set(self.capabilities)
        incoming = set(permissions) & caps
        effective: dict[str, dict[str, Any]] = {}
        for remote in roots:
            local = self.local_roots.get(str(remote.get("id", "")))
            # No server-supplied path becomes a local root, even with the same id.
            # DEC-003: never mkdir a path the device did not already share.
            if local is None or os.path.normcase(str(remote.get("path"))) != os.path.normcase(
                local["path"]
            ):
                continue
            effective[local["id"]] = {
                **local,
                "read": local["read"] and bool(remote.get("read")),
                "write": local["write"] and bool(remote.get("write")),
            }
        with self._policy_lock:
            if "command_exec" in self.permissions and "command_exec" not in incoming:
                self.stop_jobs()
            self.grant_version = grant_version
            # 0005: remote grants may expand up to capabilities; grow local consent accordingly.
            self.local_permissions |= incoming
            self.permissions = incoming
            self.roots = effective

    def apply_grant_proposal(
        self, permissions: list[str], roots: list[dict[str, Any]], *, allow_new_roots: bool = False
    ) -> None:
        """Local confirm path: accept desired grants within capabilities."""
        caps = set(self.capabilities)
        if not set(permissions) <= caps:
            raise DeviceExecutionError("unsupported grant proposal capability")
        approved = {}
        for remote in roots:
            local = self.local_roots.get(str(remote.get("id", "")))
            if local is None and not allow_new_roots:
                raise DeviceExecutionError("ROOT_NOT_ALLOWED")
            if (
                not allow_new_roots
                and local is not None
                and os.path.normcase(str(remote.get("path"))) != os.path.normcase(local["path"])
            ):
                raise DeviceExecutionError("ROOT_MKDIR_FORBIDDEN")
            if allow_new_roots:
                path = Path(remote["path"])
                if not path.is_absolute():
                    raise DeviceExecutionError("shared root must be absolute")
                _reject_links(path)
                if not path.is_dir():
                    raise DeviceExecutionError("shared root must be an existing directory")
                if self._is_private(path):
                    raise DeviceExecutionError(
                        "device credentials, approvals and runtime are private"
                    )
                approved[remote["id"]] = {**remote, "path": str(path)}
        self.local_roots.update(approved)
        self.local_permissions |= set(permissions) & caps

    def _authorize(self, action: str, grant_version: int, permissions: list[str]) -> None:
        if grant_version != self.grant_version:
            raise DeviceExecutionError("stale device grant")
        required: set[str]
        if action in {"ping", "status"}:
            required = set()
        elif action in {"files.list", "files.stat", "files.read"}:
            required = {"files_read"}
        elif action.startswith(("fs.", "git.")):
            if self.trust_mode != "owner":
                raise DeviceExecutionError("native filesystem requires device trust")
            required = {
                "files_read"
                if action in {"fs.list", "fs.stat", "fs.read", "fs.glob", "fs.grep", "git.snapshot"}
                or action.startswith("fs.download.")
                else "files_write"
            }
        elif action.startswith("files.write_"):
            required = {"files_write"}
        elif action == "desktop.capture":
            required = {"desktop_view"}
        elif action == "desktop.input":
            required = {"desktop_view", "desktop_control"}
        elif action == "command.run":
            required = {"command_exec"}
        elif action.startswith("jobs."):
            if self.trust_mode != "owner" or self._job_supervisor is None:
                raise DeviceExecutionError("Jobs require a trusted device with durable storage")
            required = {"command_exec" if action in {"jobs.start", "jobs.cancel"} else "files_read"}
        elif action.startswith("terminal."):
            if self.trust_mode != "owner":
                raise DeviceExecutionError("native terminal requires device trust")
            required = {"command_exec"}
        elif action.startswith("browser."):
            if self.trust_mode != "owner" or self.state_dir is None:
                raise DeviceExecutionError(
                    "device browser requires device trust and private storage"
                )
            required = {"command_exec"}
        elif action in {"capabilities.discover", "capabilities.skill.inspect"}:
            if self.trust_mode != "owner":
                raise DeviceExecutionError("device capability discovery requires device trust")
            required = {"files_read"}
        elif action.startswith("acp."):
            required = {"acp_run"}
        else:
            raise DeviceExecutionError("unsupported device action")
        if not required <= set(self.capabilities):
            raise DeviceExecutionError("device capability unavailable")
        if not required <= self.permissions & set(permissions):
            raise DeviceExecutionError("device permission denied")

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
        if self._is_private(path):
            raise DeviceExecutionError("device credentials, approvals and runtime are private")
        return path

    def _is_private(self, path: Path) -> bool:
        resolved = path.resolve()
        return any(resolved.is_relative_to(private) for private in self._private_paths)

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
        if action.startswith(("acp.", "terminal.", "browser.")):
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
        if action == "jobs.start":
            params = {**params, "idempotency_key": params.get("idempotency_key") or operation_id}
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
            if action in {
                "files.read",
                "fs.read",
                "fs.grep",
                "jobs.logs",
                "git.snapshot",
                "fs.download.chunk",
            }:
                receipt = {
                    key: result[key]
                    for key in (
                        "path",
                        "size",
                        "offset",
                        "next_offset",
                        "job_id",
                        "status",
                        "truncated",
                    )
                    if key in result
                }
                self._journal[operation_id]["result_retained"] = False
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
        if action.startswith("browser."):
            from octop.infra.devices.browser import DeviceBrowsers

            if self._browsers is None:
                assert self.state_dir is not None
                self._browsers = DeviceBrowsers(self.state_dir / "browser")
            try:
                return await self._browsers.call(action, params)
            except Exception as exc:
                raise DeviceExecutionError(str(exc)[:1000]) from exc
        if action in {"capabilities.discover", "capabilities.skill.inspect"}:
            from octop.infra.devices.capabilities import discover, inspect_skill

            if action == "capabilities.discover":
                return await asyncio.to_thread(discover)
            return await asyncio.to_thread(
                inspect_skill,
                str(params.get("source") or ""),
                str(params.get("slug") or ""),
                str(params.get("digest") or ""),
            )
        if action.startswith("terminal."):
            from octop.infra.devices.terminal import DeviceTerminals

            if self._terminals is None:
                self._terminals = DeviceTerminals()
            directory = (
                self.command_directory(params) if action == "terminal.open" else self.working_dir
            )
            return await self._terminals.call(action, params, directory)
        if action.startswith("jobs."):
            supervisor = self._job_supervisor
            if supervisor is None:
                raise DeviceExecutionError("Job storage unavailable")
            version, permissions = self.grant_version, list(self.permissions)

            def run_job_operation() -> dict[str, Any]:
                if action == "jobs.start":
                    # Freeze authorization and launch under the same policy lock.
                    with self._policy_lock:
                        self._authorize(action, version, permissions)
                        return supervisor.start(params, self.command_directory(params))
                if action == "jobs.list":
                    return supervisor.list(params.get("offset", 0), params.get("limit", 200))
                job_id = str(params.get("job_id") or "")
                if action == "jobs.status":
                    return supervisor.status(job_id)
                if action == "jobs.logs":
                    return supervisor.logs(
                        job_id, params.get("offset", 0), params.get("length", 65536)
                    )
                if action == "jobs.cancel":
                    return supervisor.cancel(job_id)
                raise DeviceExecutionError("unsupported Job action")

            worker = asyncio.create_task(asyncio.to_thread(run_job_operation))
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                # Cancellation of the transport cannot mislabel an accepted Job
                # or implicitly terminate it. Preserve its real launch receipt.
                while not worker.done():
                    try:
                        await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        continue
                return worker.result()
            except (OSError, ValueError) as exc:
                raise DeviceExecutionError(str(exc)) from exc
        if action.startswith(("fs.", "git.")):
            from octop.infra.devices.filesystem import NativeFileSystem

            if action.startswith(("fs.upload.", "fs.download.")) and self._transfers is None:
                from octop.infra.devices.transfers import NativeTransfers

                if self.state_dir is None:
                    raise DeviceExecutionError("native transfers require private runtime storage")
                self._transfers = NativeTransfers(self.state_dir)
                self._transfer_reaper = asyncio.create_task(self._reap_transfers())

            cancelled = threading.Event()
            version, permissions = self.grant_version, list(self.permissions)

            @contextlib.contextmanager
            def commit() -> Any:
                with self._policy_lock:
                    if cancelled.is_set():
                        raise DeviceExecutionError("operation cancelled before file commit")
                    self._authorize(action, version, permissions)
                    yield

            raw = params.get("cwd") or str(self.working_dir)
            if not isinstance(raw, str) or "\x00" in raw:
                raise DeviceExecutionError("invalid filesystem working directory")
            directory = Path(raw).expanduser()
            if not directory.is_absolute():
                directory = self.working_dir / directory

            def native_operation() -> dict[str, Any]:
                if action.startswith(("fs.upload.", "fs.download.")):
                    assert self._transfers is not None
                    return self._transfers.execute(action, params, directory, commit)
                if action.startswith("git."):
                    from octop.infra.utils.git_workbench import git_snapshot, restore_file

                    repository = str(params.get("repository") or ".")
                    if action == "git.snapshot":
                        return git_snapshot(directory, repository, native=True)
                    if action == "git.restore" and self.state_dir:
                        backup = restore_file(
                            directory,
                            repository,
                            str(params.get("path") or ""),
                            str(params.get("expected_hash") or ""),
                            self.state_dir / "recovery",
                            native=True,
                            commit=commit,
                        )
                        return {"recovery_copy": backup}
                    raise DeviceExecutionError(
                        "unsupported Git action or recovery storage unavailable"
                    )
                return NativeFileSystem(directory, commit=commit).execute(action, params)

            worker = asyncio.create_task(asyncio.to_thread(native_operation))
            try:
                try:
                    return await asyncio.shield(worker)
                except asyncio.CancelledError:
                    cancelled.set()
                    # Threads cannot be killed. Wait for their actual outcome:
                    # a completed commit is completed, never a cancelled receipt.
                    while not worker.done():
                        try:
                            await asyncio.shield(worker)
                        except asyncio.CancelledError:
                            continue
                        except DeviceExecutionError:
                            break
                    try:
                        return worker.result()
                    except DeviceExecutionError as exc:
                        if "cancelled before file commit" in str(exc):
                            raise asyncio.CancelledError from exc
                        raise
            except (OSError, ValueError, KeyError) as exc:
                raise DeviceExecutionError(str(exc)) from exc
        if action.startswith("acp."):
            if self._acp is None:
                self._acp = DeviceACPProcesses()
            session_id = str(params.get("session_id", ""))
            if action == "acp.open":
                root = self.roots.get(str(params.get("root_id", "")))
                if self.trust_mode != "owner" and (
                    root is None or not root["read"] or not root["write"]
                ):
                    raise DeviceExecutionError("ACP requires a writable shared root")
                return await self._acp.open(
                    cast(str, params.get("command")),
                    cast(list[str], params.get("args")),
                    self.command_directory(params),
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
                "trust_mode": self.trust_mode,
                "working_dir": str(self.working_dir),
                **({"system": _system_details()} if action == "status" else {}),
            }
        if action in {"files.list", "files.stat", "files.read", "files.write_begin"}:
            root_id = str(params.get("root_id", ""))
            relative = params.get("path", "")
            path = self._path(root_id, relative, write=action == "files.write_begin")
            if action == "files.list":
                entries = []
                for item in sorted(path.iterdir(), key=lambda entry: entry.name.casefold()):
                    # Links are neither followed nor advertised as accessible files.
                    if _is_link(item) or self._is_private(item):
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
                    with upload.temporary.open("ab") as upload_stream:
                        upload_stream.write(data)
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
        if action.startswith("desktop."):
            return await self._desktop_operation(action, params)
        if action == "command.run":
            return await self._command(params)
        raise DeviceExecutionError("unsupported device action")

    async def _desktop_operation(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        from octop.infra.devices.desktop import DeviceDesktop

        if self._desktop is None:
            self._desktop = DeviceDesktop()
        cancelled = threading.Event()
        version, permissions = self.grant_version, list(self.permissions)

        @contextlib.contextmanager
        def guard() -> Any:
            with self._policy_lock:
                if cancelled.is_set():
                    raise DeviceExecutionError(
                        "desktop operation cancelled before input or frame delivery"
                    )
                self._authorize(action, version, permissions)
                yield

        worker = asyncio.create_task(self._desktop.call(action, params, guard))
        try:
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                cancelled.set()
                # Reject queued input; if OS input has already completed, keep
                # its real receipt and never replay it after a transport timeout.
                while not worker.done():
                    try:
                        await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        continue
                    except (ValueError, DeviceExecutionError):
                        break
                try:
                    return worker.result()
                except DeviceExecutionError as exc:
                    if cancelled.is_set() and "cancelled before" in str(exc):
                        raise asyncio.CancelledError from exc
                    raise
        except ValueError as exc:
            raise DeviceExecutionError(str(exc)) from exc

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
        cwd = self.command_directory(params)
        spawn: dict[str, Any] = {
            "cwd": cwd,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        if os.name == "nt":
            spawn["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW | 0x4  # type: ignore[attr-defined, unused-ignore]
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
        job: WindowsJob | None = None
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
                try:
                    job = WindowsJob(process.pid)
                except ProcessScopeError as exc:
                    raise DeviceExecutionError(str(exc)) from exc
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

    async def _reap_transfers(self) -> None:
        while True:
            await asyncio.sleep(60)
            if self._transfers is not None:
                with contextlib.suppress(OSError):
                    await asyncio.to_thread(self._transfers.reap)

    async def close(self, *, preserve_terminals: bool = False) -> None:
        if self._browsers is not None and not preserve_terminals:
            await self._browsers.close_all()
        if self._terminals is not None and not preserve_terminals:
            await self._terminals.close_all()
        if self._acp is not None:
            await self._acp.close_all()
        for operation_id in list(self._active):
            await self.cancel(operation_id)
        if not preserve_terminals and self._transfers is not None:
            if self._transfer_reaper is not None:
                self._transfer_reaper.cancel()
                await asyncio.gather(self._transfer_reaper, return_exceptions=True)
                self._transfer_reaper = None
            await asyncio.to_thread(self._transfers.close)
        self.abort_uploads()
        if self._desktop is not None:
            await self._desktop.close()
            self._desktop = None
