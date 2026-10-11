from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from octop.infra.devices.executor import CHUNK_SIZE, DeviceExecutionError, DeviceExecutor


def make_executor(tmp_path, *, read_only=False, command=False, state=False):
    root = tmp_path / "shared"
    root.mkdir(exist_ok=True)
    roots = [
        {"id": "shared", "name": "Shared", "path": str(root), "read": True, "write": not read_only}
    ]
    permissions = ["files_read"] + ([] if read_only else ["files_write"])
    executor = DeviceExecutor(
        permissions,
        roots,
        state_dir=tmp_path / "state" if state else None,
        command_enabled=command,
    )
    executor.update_grants(1, list(executor.local_permissions), roots)
    return executor, root


async def call(executor, action, params, operation_id=None):
    return await executor.execute(
        operation_id or uuid.uuid4().hex,
        action,
        params,
        grant_version=executor.grant_version,
        permissions=list(executor.permissions),
    )


async def begin(executor, data, path="received.bin"):
    return (
        await call(
            executor,
            "files.write_begin",
            {
                "root_id": "shared",
                "path": path,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            },
        )
    )["upload_id"]


async def test_ordered_verified_atomic_file_round_trip(tmp_path):
    executor, root = make_executor(tmp_path, state=True)
    data = b"a" * CHUNK_SIZE + b"last chunk"
    upload = await begin(executor, data)
    assert not (root / "received.bin").exists()
    for offset in range(0, len(data), CHUNK_SIZE):
        result = await call(
            executor,
            "files.write_chunk",
            {
                "upload_id": upload,
                "offset": offset,
                "data_b64": base64.b64encode(data[offset : offset + CHUNK_SIZE]).decode(),
            },
        )
        assert result["bytes_done"] == min(offset + CHUNK_SIZE, len(data))
    committed = await call(executor, "files.write_commit", {"upload_id": upload})
    assert committed == {
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "path": "received.bin",
    }
    assert (root / "received.bin").read_bytes() == data
    assert not list(root.glob(".octop-upload-*"))
    listing = await call(executor, "files.list", {"root_id": "shared", "path": ""})
    assert [entry["name"] for entry in listing["entries"]] == ["received.bin"]
    read = await call(
        executor, "files.read", {"root_id": "shared", "path": "received.bin", "offset": CHUNK_SIZE}
    )
    assert base64.b64decode(read["data_b64"]) == b"last chunk"
    assert read["eof"] is True
    info = await call(executor, "files.stat", {"root_id": "shared", "path": "received.bin"})
    assert info["sha256"] == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize(
    "path",
    [
        "../secret",
        "a/../../secret",
        "/secret",
        "C:\\secret",
        "C:secret",
        "\\\\host\\share",
        "a\\..\\secret",
        "file:stream",
        "a\x00b",
    ],
)
async def test_rejects_cross_platform_path_escape(tmp_path, path):
    executor, _ = make_executor(tmp_path)
    with pytest.raises(DeviceExecutionError):
        await call(executor, "files.read", {"root_id": "shared", "path": path})


async def test_symlink_escape_rejected_for_read_and_commit(tmp_path):
    executor, root = make_executor(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("private")
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is not available to this OS user")
    with pytest.raises(DeviceExecutionError, match="symlink"):
        await call(executor, "files.read", {"root_id": "shared", "path": "link/secret"})
    assert (await call(executor, "files.list", {"root_id": "shared"}))["entries"] == []
    (root / "nested").mkdir()
    upload = await begin(executor, b"x", "nested/new")
    await call(
        executor, "files.write_chunk", {"upload_id": upload, "offset": 0, "data_b64": "eA=="}
    )
    (root / "nested").rename(root / "moved")
    (root / "nested").symlink_to(outside, target_is_directory=True)
    with pytest.raises(DeviceExecutionError, match="symlink"):
        await call(executor, "files.write_commit", {"upload_id": upload})
    assert not (outside / "new").exists()
    await executor.close()


async def test_windows_reparse_paths_rejected_even_without_symlink_mode(tmp_path, monkeypatch):
    executor, root = make_executor(tmp_path)
    (root / "secret").write_text("private")
    original = Path.lstat

    def reparse(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == root:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info

    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(DeviceExecutionError, match="reparse"):
        await call(executor, "files.read", {"root_id": "shared", "path": "secret"})


async def test_read_only_and_ungranted_inputs_commands_denied(tmp_path):
    executor, root = make_executor(tmp_path, read_only=True)
    (root / "readme").write_text("allowed")
    assert (await call(executor, "files.stat", {"root_id": "shared", "path": "readme"}))[
        "size"
    ] == 7
    for action, params in [
        (
            "files.write_begin",
            {
                "root_id": "shared",
                "path": "new",
                "size": 0,
                "sha256": hashlib.sha256(b"").hexdigest(),
            },
        ),
        ("desktop.input", {"kind": "type", "text": "hello"}),
        ("command.run", {"argv": [sys.executable, "-c", "print('denied')"], "root_id": "shared"}),
    ]:
        with pytest.raises(DeviceExecutionError, match="permission"):
            await call(executor, action, params)
    assert not (root / "new").exists()


async def test_remote_grant_cannot_expand_consent_or_replace_root(tmp_path):
    executor, root = make_executor(tmp_path, read_only=True)
    (root / "file").write_text("allowed")
    changed = [{"id": "shared", "path": str(tmp_path), "read": True, "write": True}]
    executor.update_grants(
        2, ["files_read", "files_write", "desktop_control", "command_exec"], changed
    )
    assert executor.permissions == {"files_read"}
    with pytest.raises(DeviceExecutionError, match="root permission"):
        await call(executor, "files.read", {"root_id": "shared", "path": "file"})
    with pytest.raises(DeviceExecutionError, match="stale"):
        await executor.execute("old", "ping", {}, grant_version=1, permissions=[])


async def test_bad_order_size_checksum_and_collision_do_not_commit(tmp_path):
    executor, root = make_executor(tmp_path)
    upload = await begin(executor, b"abc")
    with pytest.raises(DeviceExecutionError, match="ordered"):
        await call(
            executor, "files.write_chunk", {"upload_id": upload, "offset": 1, "data_b64": "YQ=="}
        )
    assert not list(root.glob(".octop-upload-*"))
    upload = await begin(executor, b"abc")
    await call(
        executor, "files.write_chunk", {"upload_id": upload, "offset": 0, "data_b64": "eHl6"}
    )
    with pytest.raises(DeviceExecutionError, match="checksum"):
        await call(executor, "files.write_commit", {"upload_id": upload})
    assert not (root / "received.bin").exists()
    upload = await begin(executor, b"abc")
    await call(
        executor, "files.write_chunk", {"upload_id": upload, "offset": 0, "data_b64": "YWJj"}
    )
    (root / "received.bin").write_bytes(b"existing")
    with pytest.raises(DeviceExecutionError):
        await call(executor, "files.write_commit", {"upload_id": upload})
    assert (root / "received.bin").read_bytes() == b"existing"
    assert not list(root.glob(".octop-upload-*"))
    with pytest.raises(DeviceExecutionError, match="exists"):
        await begin(executor, b"overwriting")


async def test_chunk_limits_abort_and_cancel_cleanup(tmp_path):
    executor, root = make_executor(tmp_path)
    upload = await begin(executor, b"large")
    with pytest.raises(DeviceExecutionError, match="chunk"):
        await call(
            executor,
            "files.write_chunk",
            {
                "upload_id": upload,
                "offset": 0,
                "data_b64": base64.b64encode(b"x" * (CHUNK_SIZE + 1)).decode(),
            },
        )
    assert not list(root.glob(".octop-upload-*"))
    data = b"small"
    params = {
        "root_id": "shared",
        "path": "received.bin",
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    await call(executor, "files.write_begin", params, "cancel-upload")
    await executor.cancel("cancel-upload")
    assert not list(root.glob(".octop-upload-*"))
    upload = await begin(executor, b"small")
    assert (await call(executor, "files.write_abort", {"upload_id": upload})) == {"aborted": True}
    assert not list(root.glob(".octop-upload-*"))
    (root / "file").write_bytes(b"x")
    with pytest.raises(DeviceExecutionError, match="length"):
        await call(
            executor, "files.read", {"root_id": "shared", "path": "file", "length": CHUNK_SIZE + 1}
        )


async def test_restart_cleans_incomplete_upload(tmp_path):
    executor, root = make_executor(tmp_path, state=True)
    await begin(executor, b"unfinished")
    assert list(root.glob(".octop-upload-*"))
    restarted, _ = make_executor(tmp_path, state=True)
    assert not list(root.glob(".octop-upload-*"))
    assert not (root / "received.bin").exists()
    await restarted.close()


async def test_persisted_command_id_runs_once_and_unknown_is_never_replayed(tmp_path):
    executor, root = make_executor(tmp_path, command=True, state=True)
    script = "from pathlib import Path; p=Path('counter'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')"
    params = {"root_id": "shared", "argv": [sys.executable, "-c", script]}
    first = await call(executor, "command.run", params, "once")
    assert first["returncode"] == 0
    restarted, _ = make_executor(tmp_path, command=True, state=True)
    assert await call(restarted, "command.run", params, "once") == first
    assert (root / "counter").read_text() == "1"
    with pytest.raises(DeviceExecutionError, match="reused"):
        await call(
            restarted, "command.run", {**params, "argv": [sys.executable, "-c", "pass"]}, "once"
        )
    journal = json.loads((tmp_path / "state" / "operations.json").read_text())
    journal["once"]["state"] = "running"
    (tmp_path / "state" / "operations.json").write_text(json.dumps(journal))
    uncertain, _ = make_executor(tmp_path, command=True, state=True)
    with pytest.raises(DeviceExecutionError, match="unknown"):
        await call(uncertain, "command.run", params, "once")
    assert (root / "counter").read_text() == "1"
    assert uncertain.reconciliation_results()[0]["ok"] is False


async def test_command_argv_is_literal_cwd_confined_output_bounded(tmp_path):
    executor, root = make_executor(tmp_path, command=True)
    argument = "hello; echo injected & $(something)"
    result = await call(
        executor,
        "command.run",
        {
            "root_id": "shared",
            "argv": [
                sys.executable,
                "-c",
                "import os,sys;print(os.getcwd());print(sys.argv[1]);print('x'*1100000)",
                argument,
            ],
        },
    )
    assert result["returncode"] == 0
    assert str(root) in result["stdout"]
    assert argument in result["stdout"]
    assert len(result["stdout"].encode()) <= CHUNK_SIZE
    assert result["truncated"] is True
    with pytest.raises(DeviceExecutionError, match="root"):
        await call(
            executor, "command.run", {"root_id": "unshared", "argv": [sys.executable, "-c", "pass"]}
        )


@pytest.mark.parametrize("kind", ["unicode", "controls", "invalid_utf8"])
async def test_command_output_fits_json_wire_budget(tmp_path, kind):
    from octop.infra.devices.executor import OUTPUT_LIMIT
    from octop.infra.devices.protocol import MAX_FRAME

    executor, _ = make_executor(tmp_path, command=True)
    data = {
        "unicode": "bytes([228,184,173])*349526",
        "controls": "bytes([0])*1048576",
        "invalid_utf8": "bytes([255])*1048576",
    }[kind]
    result = await call(
        executor,
        "command.run",
        {
            "root_id": "shared",
            "argv": [
                sys.executable,
                "-c",
                f"import sys; data={data};sys.stdout.buffer.write(data);sys.stderr.buffer.write(data)",
            ],
        },
    )
    for stream in ("stdout", "stderr"):
        assert len(json.dumps(result[stream], ensure_ascii=False).encode("utf-8")) <= OUTPUT_LIMIT
    frame = json.dumps(
        {"type": "result", "id": "bounded", "ok": True, "result": result}, ensure_ascii=False
    )
    assert len(frame.encode("utf-8")) <= MAX_FRAME
    assert result["returncode"] == 0
    assert result["truncated"] is True


async def test_legacy_command_journal_replay_and_reconcile_are_wire_bounded(tmp_path):
    from octop.infra.devices.executor import OUTPUT_LIMIT
    from octop.infra.devices.protocol import MAX_FRAME

    executor, _ = make_executor(tmp_path, command=True, state=True)
    params = {"root_id": "shared", "argv": [sys.executable, "-c", "print('once')"]}
    await call(executor, "command.run", params, "legacy-once")
    journal_path = tmp_path / "state" / "operations.json"
    journal = json.loads(journal_path.read_text())
    journal["legacy-once"]["result"].update(
        stdout="\x00" * (OUTPUT_LIMIT // 2), stderr="\ufffd" * OUTPUT_LIMIT, truncated=False
    )
    journal_path.write_text(json.dumps(journal))

    restarted, _ = make_executor(tmp_path, command=True, state=True)
    replay = await call(restarted, "command.run", params, "legacy-once")
    assert replay["truncated"] is True
    for stream in ("stdout", "stderr"):
        assert len(json.dumps(replay[stream], ensure_ascii=False).encode()) <= OUTPUT_LIMIT
    receipts = json.dumps(
        {"type": "reconcile", "results": restarted.reconciliation_results()}, ensure_ascii=False
    )
    assert len(receipts.encode()) <= MAX_FRAME


async def test_commit_rejects_directory_replaced_during_hash(tmp_path, monkeypatch):
    import shutil

    executor, root = make_executor(tmp_path)
    nested = root / "nested"
    nested.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    probe = root / "symlink-probe"
    try:
        probe.symlink_to(outside, target_is_directory=True)
        probe.unlink()
    except OSError:
        pytest.skip("symlink creation is not available to this OS user")
    upload = await begin(executor, b"checked", "nested/received")
    await call(
        executor,
        "files.write_chunk",
        {"upload_id": upload, "offset": 0, "data_b64": "Y2hlY2tlZA=="},
    )
    original = executor._sha256
    temporary = executor._uploads[upload].temporary

    async def replace_parent(path):
        digest = await original(path)
        shutil.copyfile(temporary, outside / temporary.name)
        nested.rename(root / "moved")
        nested.symlink_to(outside, target_is_directory=True)
        return digest

    monkeypatch.setattr(executor, "_sha256", replace_parent)
    try:
        with pytest.raises(DeviceExecutionError):
            await call(executor, "files.write_commit", {"upload_id": upload})
        assert not (outside / "received").exists()
    finally:
        await executor.close()
        if nested.is_symlink():
            nested.unlink()


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX no-follow directory handles")
async def test_commit_rejects_temporary_replaced_at_atomic_link(tmp_path, monkeypatch):
    executor, root = make_executor(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"untouched")
    upload = await begin(executor, b"checked")
    await call(
        executor,
        "files.write_chunk",
        {"upload_id": upload, "offset": 0, "data_b64": "Y2hlY2tlZA=="},
    )
    temporary = executor._uploads[upload].temporary
    original = os.link

    def replace_source(source, destination, **kwargs):
        # Mutate the source after the last path check, at the OS commit seam.
        temporary.unlink()
        temporary.symlink_to(outside)
        return original(source, destination, **kwargs)

    monkeypatch.setattr(os, "link", replace_source)
    with pytest.raises(DeviceExecutionError, match="temporary file changed"):
        await call(executor, "files.write_commit", {"upload_id": upload})
    assert not (root / "received.bin").exists()
    assert not (root / "received.bin").is_symlink()
    assert outside.read_bytes() == b"untouched"
    assert not temporary.is_symlink()


def pid_alive(pid):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A stopped child can remain a zombie until the platform init reaps it.
    proc_stat = Path(f"/proc/{pid}/stat")
    return not (proc_stat.exists() and proc_stat.read_text().split()[2] == "Z")


@pytest.mark.parametrize("cancel", [False, True])
async def test_command_timeout_cancel_stops_parent_and_child(tmp_path, cancel):
    executor, root = make_executor(tmp_path, command=True)
    script = "import subprocess,sys,time;from pathlib import Path;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);Path('child.pid').write_text(str(p.pid));Path('parent.pid').write_text(str(__import__('os').getpid()));time.sleep(60)"
    task = asyncio.create_task(
        call(
            executor,
            "command.run",
            {
                "root_id": "shared",
                "argv": [sys.executable, "-c", script],
                "timeout": 1 if not cancel else 60,
            },
            "process",
        )
    )
    for _ in range(100):
        if (root / "parent.pid").exists():
            break
        await asyncio.sleep(0.02)
    assert (root / "parent.pid").exists()
    parent = int((root / "parent.pid").read_text())
    child = int((root / "child.pid").read_text())
    if cancel:
        await executor.cancel("process")
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(DeviceExecutionError, match="timed out"):
            await task
    for _ in range(100):
        if not pid_alive(parent) and not pid_alive(child):
            break
        await asyncio.sleep(0.02)
    assert not pid_alive(parent)
    assert not pid_alive(child)


async def test_headless_linux_does_not_advertise_desktop(tmp_path, monkeypatch):
    monkeypatch.setattr("octop.infra.devices.executor.platform.system", lambda: "Linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    executor = DeviceExecutor([], [], desktop_enabled=True, control_enabled=True)
    executor.update_grants(1, ["desktop_view", "desktop_control"], [])
    assert "desktop_view" not in executor.capabilities
    assert "desktop_control" not in executor.capabilities
    with pytest.raises(DeviceExecutionError, match="unavailable"):
        await call(executor, "desktop.capture", {})


async def test_capture_is_not_persisted_and_duplicate_does_not_capture_again(tmp_path, monkeypatch):
    from octop.infra.desktop.capture import ScreenCapture

    executor = DeviceExecutor([], [], state_dir=tmp_path / "state", desktop_enabled=True)
    executor.update_grants(1, ["desktop_view"], [])
    monkeypatch.setattr(DeviceExecutor, "capabilities", property(lambda self: ["desktop_view"]))
    captured = []

    def capture(self, **kwargs):
        captured.append(1)
        return SimpleNamespace(jpeg_b64="private-image-data", width=100, height=50)

    monkeypatch.setattr(ScreenCapture, "capture_jpeg", capture)
    assert (await call(executor, "desktop.capture", {}, "capture"))[
        "jpeg_b64"
    ] == "private-image-data"
    assert "private-image-data" not in (tmp_path / "state" / "operations.json").read_text()
    with pytest.raises(DeviceExecutionError, match="not retained"):
        await call(executor, "desktop.capture", {}, "capture")
    assert captured == [1]
