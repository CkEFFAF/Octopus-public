"""In-memory metrics counters."""

from __future__ import annotations

import asyncio
import math
import threading
import time
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Metrics:
    messages_total: int = 0
    stream_errors_total: int = 0
    cron_runs_total: int = 0
    cron_errors_total: int = 0
    agent_active: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def inc(self, name: str, n: int = 1) -> None:
        with self._lock:
            setattr(self, name, getattr(self, name) + n)

    def set(self, name: str, value: int) -> None:
        with self._lock:
            setattr(self, name, value)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "messages_total": self.messages_total,
                "stream_errors_total": self.stream_errors_total,
                "cron_runs_total": self.cron_runs_total,
                "cron_errors_total": self.cron_errors_total,
                "agent_active": self.agent_active,
            }


METRICS = Metrics()


_DURATIONS = (
    "archive_flush",
    "mcp_prepare",
    "mcp_wait",
    "mcp_call",
    "job_observation",
    "first_text",
    "skill_refresh",
    "event_loop_lag",
)
_CACHES = ("gateway_schema", "skill_manifest")
PERFORMANCE_WINDOW = 512


@dataclass
class PerformanceMetrics:
    """Fixed-label, process-local recent samples; no request data is retained."""

    _samples: dict[str, deque[float]] = field(
        default_factory=lambda: {name: deque(maxlen=PERFORMANCE_WINDOW) for name in _DURATIONS}
    )
    _counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_DURATIONS, 0))
    _caches: dict[str, list[int]] = field(
        default_factory=lambda: {name: [0, 0] for name in _CACHES}
    )
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def observe(self, name: str, seconds: float) -> None:
        if name not in self._samples or not math.isfinite(seconds) or seconds < 0:
            return
        with self._lock:
            self._samples[name].append(seconds)
            self._counts[name] += 1

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.observe(name, time.perf_counter() - started)

    def cache(self, name: str, *, hit: bool) -> None:
        if name not in self._caches:
            return
        with self._lock:
            self._caches[name][0 if hit else 1] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            durations = {}
            for name, samples in self._samples.items():
                values = sorted(samples)
                durations[name] = {
                    "count": self._counts[name],
                    "sample_count": len(values),
                    "mean_seconds": sum(values) / len(values) if values else None,
                    "p50_seconds": values[math.ceil(len(values) * 0.50) - 1] if values else None,
                    "p95_seconds": values[math.ceil(len(values) * 0.95) - 1] if values else None,
                    "max_seconds": values[-1] if values else None,
                }
            return {
                "scope": "process",
                "window_size": PERFORMANCE_WINDOW,
                "durations": durations,
                "caches": {
                    name: {
                        "hits": hits,
                        "misses": misses,
                        "hit_rate": hits / (hits + misses) if hits + misses else None,
                    }
                    for name, (hits, misses) in self._caches.items()
                },
            }


PERFORMANCE = PerformanceMetrics()


async def sample_event_loop_lag() -> None:
    started = time.perf_counter()
    await asyncio.sleep(0.05)
    PERFORMANCE.observe("event_loop_lag", max(0, time.perf_counter() - started - 0.05))
