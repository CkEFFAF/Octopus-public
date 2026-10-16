"""Regression coverage for bounded Windows state-file sharing retries."""

from __future__ import annotations

import ctypes
import errno
import os
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace

import pytest

from octop.infra.devices import state_io


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, delay: float) -> None:
        self.now += delay


def _windows_clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    clock = _Clock()
    monkeypatch.setattr(state_io, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(state_io, "time", clock)
    return clock


@pytest.mark.skipif(os.name != "nt", reason="requires real Windows sharing locks")
def test_read_recovers_after_real_windows_sharing_lock_is_released(tmp_path: Path) -> None:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    path = tmp_path / "state.json"
    path.write_text('{"status":"running"}', encoding="utf-8")
    handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
    assert handle not in (None, ctypes.c_void_p(-1).value), ctypes.get_last_error()
    observed = []

    def read_after_release() -> str:
        nonlocal handle
        try:
            return path.read_text(encoding="utf-8")
        except PermissionError as exc:
            observed.append((exc.errno, getattr(exc, "winerror", None)))
            if handle is not None:
                assert kernel.CloseHandle(handle)
                handle = None
            raise

    try:
        assert state_io.retry_file_lock(read_after_release) == '{"status":"running"}'
        assert observed and observed[0][0] == errno.EACCES
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)


@pytest.mark.parametrize("winerror", [None, 5, 32, 33])
def test_transient_windows_permission_denial_retries(
    monkeypatch: pytest.MonkeyPatch, winerror: int | None
) -> None:
    clock = _windows_clock(monkeypatch)
    error = PermissionError(errno.EACCES, "temporarily locked")
    if winerror is not None:
        error.winerror = winerror
    calls = 0

    def operation() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise error
        return "state"

    assert state_io.retry_file_lock(operation) == "state"
    assert calls == 3
    assert clock.now == pytest.approx(0.02)


def test_permanent_windows_denial_keeps_one_second_bound_and_original_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _windows_clock(monkeypatch)
    error = PermissionError(errno.EACCES, "permanently denied")

    def operation() -> None:
        raise error

    with pytest.raises(PermissionError) as caught:
        state_io.retry_file_lock(operation)
    assert caught.value is error
    assert 1 <= clock.now < 1.02


@pytest.mark.parametrize(
    ("platform", "error"),
    [
        ("posix", PermissionError(errno.EACCES, "denied")),
        ("nt", FileNotFoundError(errno.ENOENT, "missing")),
        ("nt", PermissionError(errno.EPERM, "not a sharing denial")),
        ("nt", PermissionError(999, "unrecognized error", None, 999)),
    ],
)
def test_other_failures_propagate_without_retry(
    monkeypatch: pytest.MonkeyPatch, platform: str, error: OSError
) -> None:
    clock = _windows_clock(monkeypatch)
    monkeypatch.setattr(state_io, "os", SimpleNamespace(name=platform))
    calls = 0

    def operation() -> None:
        nonlocal calls
        calls += 1
        raise error

    with pytest.raises(type(error)) as caught:
        state_io.retry_file_lock(operation)
    assert caught.value is error
    assert calls == 1
    assert clock.now == 0
