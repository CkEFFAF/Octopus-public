"""Context insights service — 0020 DEC-03 + 0021 P0-A/B contract samples."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from octop.infra.agents.threads.context_breakdown import SEGMENT_KEYS
from octop.infra.context_insights.dto import SCHEMA_VERSION
from octop.infra.context_insights.service import ContextInsightsService, _file_op
from octop.infra.errors import OctopError
from octop.infra.history.trajectory.types import TrajectoryEvent

# DEC-03 / DEC-T14 meter parity checklist (Ring ↔ Current ↔ inspect):
# 1. context-usage (no preview) delegates ContextInsightsService._breakdown
# 2. context.inspect / ChatDockContext use the same service
# 3. SEGMENT_KEYS vocabulary is shared; used_tokens / max_tokens must match


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


def _thread_row(owner: int = 1, agent_id: str = "a1") -> SimpleNamespace:
    return SimpleNamespace(user_id=owner, agent_id=agent_id, thread_id="t1")


def _repos_with_thread() -> MagicMock:
    repo = MagicMock()
    repo.thread_repo.get.return_value = _thread_row()
    repo.trajectory_event_repo.list_before.return_value = []
    repo.trajectory_event_repo.iter_for_export.return_value = iter([])
    repo.usage_repo = MagicMock()
    repo.usage_repo.thread_totals.return_value = {
        "input_tokens": 10,
        "output_tokens": 2,
        "total_tokens": 12,
        "model_calls": 1,
        "turns": 1,
        "uncached_input_tokens": 10,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "reasoning_tokens": 0,
    }
    repo.db = object()
    return repo


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
    repo = _repos_with_thread()
    repo.trajectory_event_repo.list_before.return_value = [
        _event(seq=1, payload={"input_tokens": 40}),
        _event(event_id="e2", seq=2, kind="compacted", payload={"input_tokens": 30}),
        _event(event_id="e3", seq=3, payload={"input_tokens": 50}),
    ]
    repo.trajectory_event_repo.iter_for_export.return_value = iter(
        repo.trajectory_event_repo.list_before.return_value
    )
    registry = MagicMock()
    registry.resolve_context_max_tokens.return_value = 1000
    service = ContextInsightsService(registry, repo)
    result = await service.inspect(
        owner=1, agent_id="a1", thread_id="t1", include=["breakdown", "trend", "stats", "meters"]
    )
    compute.assert_awaited_once()
    assert result["schema_version"] == SCHEMA_VERSION
    assert result["meter_source"] == "context_usage"
    assert result["breakdown"]["used_tokens"] == 120
    assert result["breakdown"]["max_tokens"] == 1000
    assert result["breakdown"]["capacity_source"] == "harness"
    assert result["breakdown"]["segments"] == [{"key": "conversation", "tokens": 120}]
    assert len(result["trend"]) == 3
    assert "scissors" in result["trend"][1]["kind_marks"]
    assert result["breakdown"]["used_tokens"] == expected.used_tokens
    assert result["stats"]["human_turns"] == 0
    assert result["stats"]["trajectory_events"] == 3
    assert "legacy_alias" in result["stats"]
    assert result["meters"]["cumulative"]["total_tokens"] == 12
    assert result["coverage"]["coverage"] in {"complete", "partial", "unavailable"}
    assert result["resolved_scope"]["subject"]["owner_user_id"] == 1


@pytest.mark.asyncio
async def test_inspect_rejects_foreign_owner() -> None:
    repo = _repos_with_thread()
    service = ContextInsightsService(MagicMock(), repo)
    with pytest.raises(OctopError):
        await service.inspect(owner=99, agent_id="a1", thread_id="t1")


@pytest.mark.asyncio
async def test_events_mapped_kind_filter() -> None:
    repo = _repos_with_thread()
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
    repo = _repos_with_thread()
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
    repo = _repos_with_thread()
    repo.trajectory_event_repo.list_before.return_value = [
        _event(seq=1, payload={"input_tokens": 40}),
        _event(event_id="e2", seq=2, payload={"input_tokens": 55}),
        _event(event_id="e3", seq=3, payload={"input_tokens": 50}),
    ]
    service = ContextInsightsService(MagicMock(), repo)
    result = await service.events(owner=1, agent_id="a1", thread_id="t1", limit=10)
    by_id = {item["event_id"]: item["token_delta"] for item in result["events"]}
    assert by_id["e1"] is None
    assert by_id["e2"] == 15
    assert by_id["e3"] == -5
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
    repo = _repos_with_thread()
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
async def test_coverage_marks_retention_gap_when_seq_starts_above_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repos_with_thread()
    events = [_event(event_id="e9", seq=9, kind="user", summary="late")]
    repo.trajectory_event_repo.list_before.return_value = events
    repo.trajectory_event_repo.iter_for_export.return_value = iter(events)
    registry = MagicMock()
    registry.resolve_context_max_tokens.return_value = 128_000
    monkeypatch.setattr(
        "octop.infra.context_insights.service.compute_context_breakdown",
        AsyncMock(
            return_value=SimpleNamespace(
                max_tokens=128_000,
                used_tokens=0,
                segments=dict.fromkeys(SEGMENT_KEYS, 0),
            )
        ),
    )
    service = ContextInsightsService(registry, repo)
    result = await service.inspect(owner=1, agent_id="a1", thread_id="t1", include=["stats"])
    assert result["coverage"]["coverage"] == "partial"
    assert "retention_gap" in result["coverage"]["reason_codes"]
    assert result["coverage"]["missing_ranges"]


@pytest.mark.asyncio
async def test_request_pages_components_without_fabricating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repos_with_thread()

    class FakeInspection:
        def __init__(self, _repos: object) -> None:
            pass

        def get(self, *_a: object, **_k: object) -> dict:
            return {
                "request_id": "r1",
                "seq": 3,
                "status": "completed",
                "turn_id": "turn-1",
                "context_id": None,
                "created_at": 1.0,
                "estimated_input_tokens": 25,
                "actual_usage": {"input_tokens": 30, "output_tokens": 2},
                "components": [
                    {
                        "kind": "user",
                        "estimated_tokens": 25,
                        "content": "hello",
                        "sha256": "abc",
                    },
                    {
                        "kind": "tool_schema",
                        "estimated_tokens": 10,
                        "content": "schema…",
                        "content_truncated": True,
                    },
                ],
                "components_truncated": False,
                "transformation": {
                    "kind": "summarization",
                    "before_estimated_tokens": 200,
                    "after_estimated_tokens": 25,
                },
            }

        def list(self, *_a: object, **_k: object) -> dict:
            return {
                "requests": [
                    {"request_id": "r0", "seq": 1, "turn_id": "turn-1", "status": "completed"},
                    {"request_id": "r1", "seq": 3, "turn_id": "turn-1", "status": "completed"},
                ],
                "has_more": False,
                "next_before": None,
            }

    monkeypatch.setattr(
        "octop.infra.context_insights.service.RequestInspectionService",
        FakeInspection,
    )
    service = ContextInsightsService(MagicMock(), repo)
    summary = await service.request(
        owner=1, agent_id="a1", thread_id="t1", request_id="r1", include_content=False, limit=10
    )
    assert summary["schema_version"] == SCHEMA_VERSION
    assert summary["request"]["tool_schema_count"] == 1
    assert len(summary["components"]) == 2
    assert "content" not in summary["components"][0]
    assert summary["components"][0]["has_retained_content"] is True
    assert len(summary["turn_steps"]) == 2
    assert summary["effective_binding"]["reason_codes"] == ["missing_execution_context"]

    with_content = await service.request(
        owner=1,
        agent_id="a1",
        thread_id="t1",
        request_id="r1",
        include_content=True,
        limit=10,
    )
    assert with_content["components"][0]["content"] == "hello"
    assert with_content["components"][1]["truncated"] is True


@pytest.mark.asyncio
async def test_trace_read_pages_tool_result_without_inventing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repos_with_thread()
    event = _event(
        event_id="tool-1",
        kind="tool",
        summary="read_file",
        payload={
            "call_id": "c1",
            "attempt_id": "c1:1",
            "name": "read_file",
            "args": {"path": "/tmp/a"},
            "result": "line1\nline2\n",
            "status": "success",
        },
    )
    repo.trajectory_event_repo.get.return_value = event
    service = ContextInsightsService(MagicMock(), repo)
    result = await service.trace_read(
        owner=1, agent_id="a1", thread_id="t1", event_id="tool-1", part="all"
    )
    assert result["event"]["call_id"] == "c1"
    assert result["event"]["attempt_id"] == "c1:1"
    assert result["event"]["status"] == "success"
    parts = {p["key"]: p for p in result["parts"]}
    assert parts["args"]["content"]
    assert parts["result"]["content"] == "line1\nline2\n"
    assert parts["result"]["missing"] is False


@pytest.mark.asyncio
async def test_tool_counts_schema_call_attempt_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repos_with_thread()
    events = [
        _event(
            event_id="t1",
            seq=1,
            kind="tool",
            payload={"call_id": "c1", "attempt_id": "c1:1", "result": "ok"},
        ),
        _event(
            event_id="t2",
            seq=2,
            kind="tool",
            payload={"call_id": "c1", "attempt_id": "c1:2", "result": "ok"},
        ),
        _event(
            event_id="t3",
            seq=3,
            kind="tool",
            payload={"call_id": "c2", "result": "ok"},
        ),
    ]
    repo.trajectory_event_repo.list_before.return_value = events
    repo.trajectory_event_repo.iter_for_export.return_value = iter(events)
    registry = MagicMock()
    registry.resolve_context_max_tokens.return_value = 128_000
    monkeypatch.setattr(
        "octop.infra.context_insights.service.compute_context_breakdown",
        AsyncMock(
            return_value=SimpleNamespace(
                max_tokens=128_000,
                used_tokens=0,
                segments=dict.fromkeys(SEGMENT_KEYS, 0),
            )
        ),
    )
    service = ContextInsightsService(registry, repo)
    result = await service.inspect(owner=1, agent_id="a1", thread_id="t1", include=["stats"])
    assert result["stats"]["logical_call_count"] == 2
    assert result["stats"]["attempt_count"] == 3
