"""Context insights service shares compute_context_breakdown (DEC-03)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from octop.infra.agents.threads.context_breakdown import SEGMENT_KEYS
from octop.infra.context_insights.service import ContextInsightsService
from octop.infra.history.trajectory.types import TrajectoryEvent


def _event(**kwargs: object) -> TrajectoryEvent:
    base = dict(
        event_id="e1",
        thread_id="t1",
        agent_id="a1",
        seq=1,
        ts=1.0,
        kind="assistant",
        turn_id="turn-1",
        request_seq=1,
        is_error=False,
        summary="hi",
        payload={},
    )
    base.update(kwargs)
    return TrajectoryEvent(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_inspect_breakdown_uses_compute_context_breakdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = SimpleNamespace(
        max_tokens=1000,
        used_tokens=120,
        segments={key: 0 for key in SEGMENT_KEYS} | {"conversation": 120},
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
