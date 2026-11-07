"""0041 — thread.changed helper: coalesce, owner isolation, no token leakage."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from octop.infra.gateway.thread_events import (
    THREAD_CHANGED_SCHEMA_VERSION,
    THREAD_CHANGED_TYPE,
    ThreadEventEmitter,
    build_turn_status_frame,
)
from octop.infra.gateway.ws.ws_hub import WebSocketHub


@pytest.mark.asyncio
async def test_emit_delivers_only_to_owner() -> None:
    hub = WebSocketHub()
    alice: list[dict[str, Any]] = []
    bob: list[dict[str, Any]] = []

    async def capture_alice(frame: dict[str, Any]) -> None:
        alice.append(frame)

    async def capture_bob(frame: dict[str, Any]) -> None:
        bob.append(frame)

    hub.register("a", capture_alice, user_id=1)
    hub.register("b", capture_bob, user_id=2)
    emitter = ThreadEventEmitter(hub)

    await emitter.emit_thread_changed(
        owner_user_id=1,
        agent_id="agent-a",
        thread_id="thr_1",
        reason="created",
    )

    assert len(alice) == 1
    assert bob == []
    frame = alice[0]
    assert frame["type"] == THREAD_CHANGED_TYPE
    assert frame["schema_version"] == THREAD_CHANGED_SCHEMA_VERSION
    assert frame["reason"] == "created"
    assert frame["agent_id"] == "agent-a"
    assert frame["thread_id"] == "thr_1"
    assert frame["run_id"] is None
    assert isinstance(frame["event_id"], str) and frame["event_id"]
    assert isinstance(frame["updated_at"], float)
    # No token / body / credential fields.
    for banned in ("token", "content", "text", "message", "api_key", "password", "args"):
        assert banned not in frame


@pytest.mark.asyncio
async def test_running_coalesce_same_phase_within_one_second() -> None:
    hub = WebSocketHub()
    frames: list[dict[str, Any]] = []

    async def capture(frame: dict[str, Any]) -> None:
        frames.append(frame)

    hub.register("c", capture, user_id=9)
    emitter = ThreadEventEmitter(hub)

    await emitter.emit_thread_changed(
        owner_user_id=9,
        agent_id="a",
        thread_id="t",
        reason="running",
        phase="llm_running",
    )
    await emitter.emit_thread_changed(
        owner_user_id=9,
        agent_id="a",
        thread_id="t",
        reason="running",
        phase="llm_running",
    )
    assert len(frames) == 1

    await emitter.emit_thread_changed(
        owner_user_id=9,
        agent_id="a",
        thread_id="t",
        reason="running",
        phase="tool_running",
    )
    assert len(frames) == 2
    assert frames[1]["reason"] == "running"
    assert "phase" not in frames[1]


@pytest.mark.asyncio
async def test_running_coalesce_expires_after_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    hub = WebSocketHub()
    frames: list[dict[str, Any]] = []

    async def capture(frame: dict[str, Any]) -> None:
        frames.append(frame)

    hub.register("c", capture, user_id=3)
    emitter = ThreadEventEmitter(hub)

    mono = {"v": 100.0}

    def fake_mono() -> float:
        return mono["v"]

    monkeypatch.setattr(time, "monotonic", fake_mono)

    await emitter.emit_thread_changed(
        owner_user_id=3, agent_id="a", thread_id="t", reason="running", phase="llm_running"
    )
    mono["v"] = 100.5
    await emitter.emit_thread_changed(
        owner_user_id=3, agent_id="a", thread_id="t", reason="running", phase="llm_running"
    )
    assert len(frames) == 1
    mono["v"] = 101.1
    await emitter.emit_thread_changed(
        owner_user_id=3, agent_id="a", thread_id="t", reason="running", phase="llm_running"
    )
    assert len(frames) == 2


@pytest.mark.asyncio
async def test_terminal_and_attention_never_dropped() -> None:
    hub = WebSocketHub()
    frames: list[dict[str, Any]] = []

    async def capture(frame: dict[str, Any]) -> None:
        frames.append(frame)

    hub.register("c", capture, user_id=4)
    emitter = ThreadEventEmitter(hub)

    for reason in ("created", "attention", "completed", "failed", "cancelled"):
        await emitter.emit_thread_changed(
            owner_user_id=4, agent_id="a", thread_id="t", reason=reason
        )
    assert [f["reason"] for f in frames] == [
        "created",
        "attention",
        "completed",
        "failed",
        "cancelled",
    ]


@pytest.mark.asyncio
async def test_suppress_thread_stops_emits() -> None:
    hub = WebSocketHub()
    frames: list[dict[str, Any]] = []

    async def capture(frame: dict[str, Any]) -> None:
        frames.append(frame)

    hub.register("c", capture, user_id=5)
    emitter = ThreadEventEmitter(hub)
    emitter.suppress_thread("thr_gone")
    await emitter.emit_thread_changed(
        owner_user_id=5, agent_id="a", thread_id="thr_gone", reason="completed"
    )
    assert frames == []


@pytest.mark.asyncio
async def test_push_failure_is_swallowed() -> None:
    class BoomHub:
        async def push_to_user(self, user_id: int, frame: dict[str, Any]) -> None:
            raise RuntimeError("socket dead")

    emitter = ThreadEventEmitter(BoomHub())  # type: ignore[arg-type]
    await emitter.emit_thread_changed(
        owner_user_id=1, agent_id="a", thread_id="t", reason="created"
    )


def test_build_turn_status_extends_steering_without_forging() -> None:
    frame = build_turn_status_frame(
        thread_id="thr_x",
        active=True,
        steering={"run_id": "run1", "phase": "llm_running"},
        last_event_at=100.0,
        active_tools=["web_search", ""],
        artifacts=[
            {"resource_id": "res_1", "version": 2},
            {"path": "/secret/abs"},  # dropped — no resource_id
        ],
    )
    assert frame["type"] == "turn_status"
    assert frame["schema_version"] == 1
    assert frame["active"] is True
    assert frame["runtime"] == {
        "phase": "llm_running",
        "run_id": "run1",
        "active_tools": ["web_search"],
        "last_event_at": 100.0,
    }
    assert frame["artifacts"] == [{"resource_id": "res_1", "version": 2}]

    idle = build_turn_status_frame(thread_id="t", active=False, steering=None)
    assert idle["runtime"] is None
    assert "artifacts" not in idle


@pytest.mark.asyncio
async def test_unknown_reason_is_ignored() -> None:
    hub = WebSocketHub()
    frames: list[dict[str, Any]] = []

    async def capture(frame: dict[str, Any]) -> None:
        frames.append(frame)

    hub.register("c", capture, user_id=1)
    emitter = ThreadEventEmitter(hub)
    await emitter.emit_thread_changed(
        owner_user_id=1,
        agent_id="a",
        thread_id="t",
        reason="bogus",  # type: ignore[arg-type]
    )
    assert frames == []


def _gateway_for_operation(
    *,
    thread_id: str = "thr_op",
    swallow_cancelled: bool = False,
) -> Any:
    """Minimal Gateway shell for iter_dashboard_operation unit tests."""
    from types import SimpleNamespace

    from octop.infra.gateway.gateway import Gateway

    gw = Gateway.__new__(Gateway)
    row = SimpleNamespace(user_id=7, agent_id="agent-x")

    class _Mgr:
        async def run_in_session(self, channel_id: str, key: str, fn: Any) -> None:
            try:
                await fn()
            except asyncio.CancelledError:
                if swallow_cancelled:
                    # operation() already emitted cancelled in its finally.
                    return
                raise

    emitted: list[dict[str, Any]] = []

    async def capture_emit(**kwargs: Any) -> None:
        emitted.append(dict(kwargs))

    gw._channel_manager = _Mgr()
    gw._ws_hub = SimpleNamespace(
        mark_turn_active=MagicMock(),
        mark_turn_idle=MagicMock(),
        push_to_thread=AsyncMock(),
    )
    gw._thread_registry = SimpleNamespace(get_thread=MagicMock(return_value=row))
    gw._dashboard_operations = set()
    gw._resume_terminal_emitted = set()
    gw._inputs = SimpleNamespace(observe=MagicMock())
    gw.emit_thread_changed = capture_emit  # type: ignore[method-assign]
    gw._emit_resume_thread_event = Gateway._emit_resume_thread_event.__get__(gw, Gateway)
    return gw, emitted, row


@pytest.mark.asyncio
async def test_operation_cancelled_emits_cancelled() -> None:
    """CancelledError must map to reason=cancelled, not completed (Medium 1)."""
    gw, emitted, _row = _gateway_for_operation(swallow_cancelled=True)

    async def source():
        raise asyncio.CancelledError()
        yield "unreachable"  # pragma: no cover

    frames = [frame async for frame in gw.iter_dashboard_operation("thr_op", source)]
    assert frames == []

    reasons = [e["reason"] for e in emitted]
    assert reasons[0] == "running"
    assert reasons[-1] == "cancelled"
    assert "completed" not in reasons
    gw._ws_hub.mark_turn_idle.assert_called_with("thr_op")


@pytest.mark.asyncio
async def test_operation_skips_terminal_when_resume_already_emitted() -> None:
    """Resume terminal emit suppresses the operation() finally duplicate (Medium 2)."""
    gw, emitted, _row = _gateway_for_operation()
    resume_seen = asyncio.Event()

    async def source():
        # Simulate HITL resume path emitting a terminal before the stream ends.
        await gw._emit_resume_thread_event(
            7,
            "agent-x",
            "thr_op",
            {"type": "run_phase", "phase": "completed", "run_id": "run-1"},
        )
        resume_seen.set()
        yield "frame"

    frames = [frame async for frame in gw.iter_dashboard_operation("thr_op", source)]
    assert frames == ["frame"]
    assert resume_seen.is_set()

    reasons = [e["reason"] for e in emitted]
    # running (op start) + completed (resume) — no second completed from finally
    assert reasons.count("completed") == 1
    assert reasons[0] == "running"
    assert reasons[1] == "completed"
    assert len(reasons) == 2
    gw._ws_hub.mark_turn_idle.assert_called()
    assert "thr_op" not in gw._resume_terminal_emitted


@pytest.mark.asyncio
async def test_operation_emits_terminal_when_resume_did_not() -> None:
    """Without a resume terminal, finally still emits completed."""
    gw, emitted, _row = _gateway_for_operation()

    async def source():
        yield "ok"

    frames = [frame async for frame in gw.iter_dashboard_operation("thr_op", source)]
    assert frames == ["ok"]
    reasons = [e["reason"] for e in emitted]
    assert reasons == ["running", "completed"]
