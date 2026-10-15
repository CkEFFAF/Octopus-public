"""GPU metrics belong only to observed Job processes; missing is not zero."""

from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import Mock

from octop.infra.devices import resources


def test_gpu_process_filter_cache_and_unknown_memory(monkeypatch: Any) -> None:
    monkeypatch.setattr(resources, "_expires", 0)
    monkeypatch.setattr(resources.shutil, "which", lambda _: "/usr/bin/nvidia-smi")
    run = Mock(
        return_value=subprocess.CompletedProcess(
            [], 0, "11, GPU-one, 120\n12, GPU-two, [N/A]\n13, GPU-other, 999\n"
        )
    )
    monkeypatch.setattr(resources.subprocess, "run", run)
    result = resources.gpu_processes({11, 12})
    assert result["status"] == "available"
    assert result["processes"] == [
        {"pid": 11, "gpu_uuid": "GPU-one", "memory_bytes": 120 * 1024**2},
        {"pid": 12, "gpu_uuid": "GPU-two", "memory_bytes": None},
    ]
    assert resources.gpu_processes({13})["processes"][0]["pid"] == 13
    assert run.call_count == 1


def test_gpu_collector_absence_and_timeout_are_unavailable(monkeypatch: Any) -> None:
    monkeypatch.setattr(resources.shutil, "which", lambda _: None)
    monkeypatch.setattr(resources, "_expires", 0)
    assert resources.gpu_processes({11})["status"] == "unavailable"
    monkeypatch.setattr(resources.shutil, "which", lambda _: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(resources, "_expires", 0)
    monkeypatch.setattr(
        resources.subprocess, "run", Mock(side_effect=subprocess.TimeoutExpired("nvidia-smi", 3))
    )
    result = resources.gpu_processes({11})
    assert result["status"] == "unavailable" and result["processes"] == []
