"""Native process scopes shared by short commands and persistent Job workers."""

from __future__ import annotations

import contextlib
import ctypes
import os

import psutil


class ProcessScopeError(RuntimeError):
    pass


class WindowsJob:
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

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined, unused-ignore]
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
            raise ProcessScopeError("cannot contain command process")
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        process = None
        try:
            if not self.kernel.SetInformationJobObject(
                self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            ):
                raise ProcessScopeError("cannot contain command process")
            process = self.kernel.OpenProcess(0x0100 | 0x0001 | 0x0800, False, pid)
            if not process or not self.kernel.AssignProcessToJobObject(self.handle, process):
                raise ProcessScopeError("cannot contain command process")
            # asyncio exposes the process but not its primary thread handle.
            # Resume only after assigning the still-suspended process to its job.
            ntdll = ctypes.WinDLL("ntdll")  # type: ignore[attr-defined, unused-ignore]
            ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
            ntdll.NtResumeProcess.restype = ctypes.c_long
            if ntdll.NtResumeProcess(process) != 0:
                raise ProcessScopeError("cannot start contained command")
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

    def pids(self) -> list[int]:
        """Query the kernel-owned process set, including reparented descendants."""
        from ctypes import wintypes

        if not self.handle:
            return []

        self.kernel.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        capacity = 64
        while capacity <= 65536:

            class ProcessList(ctypes.Structure):
                _fields_ = [
                    ("assigned", wintypes.DWORD),
                    ("count", wintypes.DWORD),
                    ("ids", ctypes.c_size_t * capacity),
                ]

            processes, required = ProcessList(), wintypes.DWORD()
            if self.kernel.QueryInformationJobObject(
                self.handle,
                3,
                ctypes.byref(processes),
                ctypes.sizeof(processes),
                ctypes.byref(required),
            ):
                return [int(pid) for pid in processes.ids[: processes.count]]
            if ctypes.get_last_error() != 234:  # type: ignore[attr-defined, unused-ignore]  # ERROR_MORE_DATA
                raise ProcessScopeError("cannot observe contained command processes")
            capacity *= 2
        raise ProcessScopeError("command process scope exceeds observation capacity")


class PosixSession:
    """Observe the launched session plus descendants seen before they detach."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.seen: dict[int, float] = {}
        with contextlib.suppress(psutil.Error):
            self.seen[pid] = psutil.Process(pid).create_time()

    def pids(self) -> list[int]:
        # Session membership survives an intermediate launcher exiting. PID
        # creation identities keep already observed detached children attached.
        for process in psutil.process_iter(["pid", "create_time"]):
            try:
                if os.getsid(process.pid) == self.pid:  # type: ignore[attr-defined, unused-ignore]
                    self.seen[process.pid] = process.create_time()
            except (ProcessLookupError, psutil.NoSuchProcess):
                continue
            except (OSError, psutil.Error) as exc:
                raise ProcessScopeError("cannot observe Job session membership") from exc
        root = self._live(self.pid)
        if root:
            with contextlib.suppress(psutil.Error):
                for child in root.children(recursive=True):
                    self.seen[child.pid] = child.create_time()
        return [pid for pid in self.seen if self._live(pid)]

    def _live(self, pid: int) -> psutil.Process | None:
        try:
            process = psutil.Process(pid)
            return (
                process
                if process.create_time() == self.seen[pid]
                and process.status() != psutil.STATUS_ZOMBIE
                else None
            )
        except psutil.NoSuchProcess:
            return None

    def close(self) -> None:
        pass
