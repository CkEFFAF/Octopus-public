"""Context insights service shares compute_context_breakdown (DEC-03)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from octop.infra.agents.threads.context_breakdown import SEGMENT_KEYS
from octop.infra.context_insights.service import ContextInsightsService, _file_op
from octop.infra.history.trajectory.types import TrajectoryEvent

# DEC-03 meter parity checklist (Ring ↔ Current ↔ inspect):
# 1. ContextWindowRing + ChatDockContext Current both call
#    octopThreadsApi.contextUsage → GET .../context-usage → compute_context_breakdown
# 2. context.inspect / ContextInsightsService._breakdown calls the same
#    compute_context_breakdown (meter_source == "context_usage")
# 3. SEGMENT_KEYS vocabulary is shared; used_tokens / max_tokens must match
#    whenever the underlying harness stamp is unchanged.
# If any consumer invents a second occupancy estimator, treat as a regression.


def _event(**kwargs: object) -> TrajectoryEvent:
    base = {
        "event_id": "e1",
        "thread_id": "t1",
        "agent_id": "a1",
        "seq": 1,
        "ts": 1.0,
        "kind": "assistant",
        "turn_id": "turn-1",
        "request_seq": 1,
        "is_error": False,
        "summary": "hi",
        "payload": {},
    }
    base.update(kwargs)
    return TrajectoryEvent(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_inspect_breakdown_uses_compute_context_breakdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = SimpleNamespace(
        max_tokens=1000,
        used_tokens=120,
        segments=dict.fromkeys(SEGMENT_KEYS, 0) | {"conversation": 120},
    )
    compute = AsyncMock(return_value=expected)
    monkeypatch.setattr(
        "octop.infra.context_insights.service.compute_context_breakdown",
        compute,
    )
    repo = MagicMock()
    repo.trajectory_event_repo.list_before.return_value = [
        _event(seq=1, payload={"input_tokens": 40}),
        _event(event_id="e2", seq=2, kind="compacted", payload={"input_tokens": 30}),
        _event(event_id="e3", seq=3, payload={"input_tokens": 50}),
    ]
    repo.usage_repo = MagicMock()
    registry = MagicMock()
    registry.resolve_context_max_tokens.return_value = 1000
    service = ContextInsightsService(registry, repo)
    result = await service.inspect(
        owner=1, agent_id="a1", thread_id="t1", include=["breakdown", "trend"]
    )
    compute.assert_awaited_once()
    assert result["meter_source"] == "context_usage"
    assert result["breakdown"]["used_tokens"] == 120
    assert result["breakdown"]["max_tokens"] == 1000
    assert result["breakdown"]["segments"] == [{"key": "conversation", "tokens": 120}]
    assert len(result["trend"]) == 3
    assert "scissors" in result["trend"][1]["kind_marks"]
    # Same-number contract vs Ring/Current: inspect must echo compute_* verbatim.
    assert result["breakdown"]["used_tokens"] == expected.used_tokens
    assert result["breakdown"]["max_tokens"] == expected.max_tokens


@pytest.mark.asyncio
async def test_events_mapped_kind_filter() -> None:
    repo = MagicMock()
    repo.trajectory_event_repo.list_before.return_value = [
        _event(seq=1, kind="user", summary="u"),
        _event(event_id="e2", seq=2, kind="compacted", summary="c"),
        _event(event_id="e3", seq=3, kind="context", summary="inj"),
    ]
    service = ContextInsightsService(MagicMock(), repo)
    result = await service.events(
        owner=1, agent_id="a1", thread_id="t1", kinds=["compact", "inject"], limit=10
    )
    kinds = {item["mapped_kind"] for item in result["events"]}
    assert kinds == {"compact", "inject"}
    assert result["has_more"] is False


@pytest.mark.asyncio
async def test_events_has_more_respects_kinds_filter() -> None:
    """has_more must not flip true merely because the unfiltered window is full."""
    repo = MagicMock()
    # 11 raw events, but only 2 match compact/inject → must not claim has_more.
    rows = [_event(event_id=f"u{i}", seq=i, kind="user", summary=f"u{i}") for i in range(1, 10)]
    rows.append(_event(event_id="c1", seq=10, kind="compacted", summary="c"))
    rows.append(_event(event_id="i1", seq=11, kind="context", summary="inj"))
    repo.trajectory_event_repo.list_before.return_value = rows
    service = ContextInsightsService(MagicMock(), repo)
    result = await service.events(
        owner=1, agent_id="a1", thread_id="t1", kinds=["compact", "inject"], limit=10
    )
    assert len(result["events"]) == 2
    assert result["has_more"] is False


@pytest.mark.asyncio
async def test_events_token_delta_is_step_delta_not_absolute() -> None:
    repo = MagicMock()
    repo.trajectory_event_repo.list_before.return_value = [
        _event(seq=1, payload={"input_tokens": 40}),
        _event(event_id="e2", seq=2, payload={"input_tokens": 55}),
        _event(event_id="e3", seq=3, payload={"input_tokens": 50}),
    ]
    service = ContextInsightsService(MagicMock(), repo)
    result = await service.events(owner=1, agent_id="a1", thread_id="t1", limit=10)
    by_id = {item["event_id"]: item["token_delta"] for item in result["events"]}
    assert by_id["e1"] is None  # first step in window: no prior baseline
    assert by_id["e2"] == 15
    assert by_id["e3"] == -5
    # Must not echo absolute input_tokens as delta.
    assert by_id["e2"] != 55
    assert by_id["e3"] != 50


@pytest.mark.asyncio
async def test_file_ops_returns_gaps_when_sparse(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRunEvents:
        def __init__(self, _db: object) -> None:
            pass

        def list(self, *_a: object, **_k: object) -> list[dict]:
            return [
                {
                    "kind": "interaction",
                    "payload": {"path": "/tmp/a.txt", "tool": "read_file"},
                },
                {
                    "kind": "interaction",
                    "payload": {"path": "/tmp/a.txt", "name": "write_file"},
                },
                {"kind": "job", "payload": {"note": "no path"}},
            ]

    monkeypatch.setattr(
        "octop.infra.context_insights.service.RunEventRepo",
        FakeRunEvents,
    )
    repo = MagicMock()
    repo.db = object()
    service = ContextInsightsService(MagicMock(), repo)
    result = await service.file_ops(owner=1, agent_id="a1", thread_id="t1")
    assert result["files"][0]["path"] == "/tmp/a.txt"
    assert result["files"][0]["reads"] == 1
    assert result["files"][0]["writes"] == 1
    assert result["gaps"] == []


def test_file_op_avoids_broad_substring_matches() -> None:
    assert _file_op("interaction", {"tool": "openai_chat", "path": "/x"}) is None
    assert _file_op("interaction", {"tool": "thread_ready", "path": "/x"}) is None
    assert _file_op("interaction", {"name": "findings_report", "path": "/x"}) is None
    assert _file_op("interaction", {"tool": "read_file"}) == "reads"
    assert _file_op("interaction", {"tool": "apply_patch"}) == "writes"
    assert _file_op("interaction", {"tool": "codebase_search"}) == "searches"
    assert _file_op("interaction", {"op": "read"}) == "reads"


@pytest.mark.asyncio
async def test_inspect_stats_include_tool_calls_and_null_cost() -> None:
    repo = MagicMock()
    repo.trajectory_event_repo.list_before.return_value = [
        _event(seq=1, kind="user", payload={"input_tokens": 10}),
        _event(event_id="t1", seq=2, kind="tool", summary="bash", payload={}),
        _event(event_id="t2", seq=3, kind="tool", summary="read", payload={}),
        _event(event_id="a1", seq=4, kind="assistant", payload={"input_tokens": 20}),
    ]
    repo.usage_repo = MagicMock()
    service = ContextInsightsService(MagicMock(), repo)
    result = await service.inspect(owner=1, agent_id="a1", thread_id="t1", include=["stats"])
    assert result["stats"]["tool_calls"] == 2
    assert result["stats"]["cost"] is None
    assert "cost_no_pricing_sot" in result["stats"]["gaps"]


@pytest.mark.asyncio
async def test_dashboard_summary_honest_gaps_and_sessions() -> None:
    usage = MagicMock()
    usage.summary.return_value = {
        "window": "last_7d",
        "range_start": 1,
        "range_end": 2,
        "total_tokens": 1000,
        "turns": 4,
        "model_calls": 4,
        "cache_hit_percent": 50,
        "buckets": [
            {"key": "2026-10-15", "label": "2026-10-15", "total_tokens": 600, "turns": 2},
            {"key": "2026-10-14", "label": "2026-10-14", "total_tokens": 400, "turns": 2},
        ],
    }
    usage.thread_rollup.return_value = [
        {
            "agent_id": "a1",
            "thread_id": "th-1",
            "input_tokens": 80,
            "cache_read_tokens": 40,
            "output_tokens": 20,
            "total_tokens": 100,
            "model_calls": 2,
            "turns": 2,
            "last_ts": 100,
        },
        {
            "agent_id": "a1",
            "thread_id": "th-2",
            "input_tokens": 10,
            "cache_read_tokens": 0,
            "output_tokens": 5,
            "total_tokens": 15,
            "model_calls": 1,
            "turns": 1,
            "last_ts": 90,
        },
    ]
    usage.count_active_threads.return_value = 2
    threads = MagicMock()
    threads.count_by_user.return_value = 9
    threads.get_many.return_value = {
        "th-1": SimpleNamespace(title="Hello", agent_id="a1", last_active=100),
    }
    repo = MagicMock()
    repo.usage_repo = usage
    repo.thread_repo = threads
    service = ContextInsightsService(MagicMock(), repo)
    result = await service.dashboard_summary(owner=7, window="last_7d", query="hello")
    assert result["kpi"]["active_sessions"] == 2
    assert result["kpi"]["total_sessions"] == 9
    assert result["kpi"]["total_tokens"] == 1000
    assert result["kpi"]["cost"] is None
    assert result["kpi"]["balance"] is None
    assert result["kpi"]["tool_calls"] is None
    assert "cost_no_pricing_sot" in result["gaps"]
    assert "balance_no_provider_sot" in result["gaps"]
    assert len(result["sessions"]) == 1  # filtered by query
    assert result["sessions"][0]["title"] == "Hello"
    assert result["sessions"][0]["cost"] is None
    assert result["by_day"][0]["cost"] is None
