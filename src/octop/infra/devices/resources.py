"""Optional NVIDIA process observations; unsupported counters stay unknown."""

from __future__ import annotations

import csv
import io
import os
import shutil
import subprocess
import threading
import time
from typing import Any

_lock = threading.Lock()
_expires = 0.0
_latest: dict[str, Any] = {}


def gpu_processes(pids: set[int]) -> dict[str, Any]:
    global _expires, _latest
    with _lock:
        if time.monotonic() >= _expires:
            _latest = _query()
            _expires = time.monotonic() + 5
        return {
            **_latest,
            "processes": [row for row in _latest.get("processes", []) if row["pid"] in pids],
        }


def _query() -> dict[str, Any]:
    observed_at = time.time()
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return {
            "status": "unavailable",
            "reason": "nvidia-smi not installed",
            "observed_at": observed_at,
        }
    try:
        result = subprocess.run(
            [
                executable,
                "--query-compute-apps=pid,gpu_uuid,used_gpu_memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        if result.returncode:
            return {
                "status": "unavailable",
                "reason": "GPU driver query failed",
                "observed_at": observed_at,
            }
        rows = []
        for values in csv.reader(io.StringIO(result.stdout)):
            if len(values) != 3:
                raise ValueError("unexpected GPU process fields")
            pid, gpu, memory = (value.strip() for value in values)
            # WDDM may report [N/A]. That is unknown memory, not zero bytes.
            rows.append(
                {
                    "pid": int(pid),
                    "gpu_uuid": gpu,
                    "memory_bytes": int(memory) * 1024 * 1024 if memory.isdecimal() else None,
                }
            )
        return {"status": "available", "observed_at": observed_at, "processes": rows}
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {
            "status": "unavailable",
            "reason": "GPU process observation unavailable",
            "observed_at": observed_at,
        }
