"""0041 — thread.changed helper: coalesce, owner isolation, no token leakage."""

from __future__ import annotations

import time
from typing import Any

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
