"""tests/unit/test_metrics.py"""

from __future__ import annotations

import math

import pytest

from octop.infra.metrics import METRICS, PERFORMANCE_WINDOW, Metrics, PerformanceMetrics


def test_metrics_inc_and_snapshot() -> None:
    m = Metrics()
    m.inc("messages_total")
    m.inc("messages_total", 4)
    m.inc("stream_errors_total")
    snap = m.snapshot()
    assert snap["messages_total"] == 5
    assert snap["stream_errors_total"] == 1
    assert snap["cron_runs_total"] == 0


def test_metrics_set() -> None:
    m = Metrics()
    m.set("agent_active", 3)
    assert m.snapshot()["agent_active"] == 3


def test_singleton_exists() -> None:
    snap = METRICS.snapshot()
    assert "messages_total" in snap
    assert "agent_active" in snap


def test_duration_window_is_bounded_and_empty_percentiles_are_unknown() -> None:
    metrics = PerformanceMetrics()
    assert metrics.snapshot()["durations"]["mcp_wait"]["p95_seconds"] is None
    for value in range(PERFORMANCE_WINDOW + 100):
        metrics.observe("mcp_wait", float(value))
    row = metrics.snapshot()["durations"]["mcp_wait"]
    assert row["count"] == PERFORMANCE_WINDOW + 100
    assert row["sample_count"] == PERFORMANCE_WINDOW
    assert row["p50_seconds"] == 100 + math.ceil(PERFORMANCE_WINDOW * 0.5) - 1
    assert row["p95_seconds"] == 100 + math.ceil(PERFORMANCE_WINDOW * 0.95) - 1
    assert row["mean_seconds"] == (100 + PERFORMANCE_WINDOW + 99) / 2


def test_invalid_samples_and_unregistered_labels_are_not_retained() -> None:
    metrics = PerformanceMetrics()
    for value in (-1, float("nan"), float("inf")):
        metrics.observe("mcp_call", value)
    metrics.observe("user-secret", 1)
    metrics.cache("credential", hit=True)
    snapshot = metrics.snapshot()
    assert snapshot["durations"]["mcp_call"]["count"] == 0
    assert "user-secret" not in snapshot["durations"]
    assert "credential" not in snapshot["caches"]


def test_measure_records_failed_calls_without_swallowing_the_error() -> None:
    metrics = PerformanceMetrics()
    with pytest.raises(ValueError, match="original"), metrics.measure("archive_flush"):
        raise ValueError("original")
    assert metrics.snapshot()["durations"]["archive_flush"]["count"] == 1


def test_cache_hits_misses_and_returned_data_are_independent() -> None:
    metrics = PerformanceMetrics()
    assert metrics.snapshot()["caches"]["gateway_schema"]["hit_rate"] is None
    metrics.cache("gateway_schema", hit=True)
    metrics.cache("gateway_schema", hit=False)
    snapshot = metrics.snapshot()
    assert snapshot["caches"]["gateway_schema"]["hit_rate"] == 0.5
    snapshot["caches"]["gateway_schema"]["hits"] = 100
    assert metrics.snapshot()["caches"]["gateway_schema"]["hits"] == 1
