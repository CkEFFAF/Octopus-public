"""0041 — notifications WS receives thread.changed; non-owner isolation; subscribe snapshot."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from tests.support.app import octop_client
from tests.support.auth import auth_header, bootstrap_admin, ensure_users
from tests.support.http import ws_connect, ws_token


@pytest.fixture
async def env(tmp_octop_home: Path) -> AsyncIterator[Any]:
    async with octop_client(tmp_octop_home) as (c, srv):
        await bootstrap_admin(c, tmp_octop_home)
        admin_auth = await auth_header(c)
        users = await ensure_users(c, admin_auth, "alice", "bob")
        yield c, srv, users["alice"], users["bob"], admin_auth


def _notifications_ws(c: Any, auth: dict[str, str] | None = None) -> Any:
    query = f"?token={ws_token(auth)}" if auth else ""
    return ws_connect(c._octop_app, f"/api/notifications/ws{query}")


async def _create_agent(c: Any, auth: dict[str, str]) -> str:
    resp = await c.post("/api/agents", headers=auth, json={"name": "sync-agent"})
    assert resp.status_code == 201, resp.text
    return resp.json()["agent_id"]


@pytest.mark.asyncio
async def test_owner_receives_thread_changed_on_create(env: Any) -> None:
    c, srv, alice_auth, _bob_auth, _admin = env
    alice = srv.user_manager.get("alice")
    assert alice is not None
    agent_id = await _create_agent(c, alice_auth)

    async with _notifications_ws(c, alice_auth) as ws:
        await ws.send_json({"type": "ping"})
        assert await ws.receive_json() == {"type": "pong"}
        resp = await c.post(f"/api/agents/{agent_id}/threads", headers=alice_auth)
        assert resp.status_code == 201, resp.text
        tid = resp.json()["thread_id"]
        frame = await ws.receive_json()
        assert frame["type"] == "thread.changed"
        assert frame["schema_version"] == 1
        assert frame["reason"] == "created"
        assert frame["thread_id"] == tid
        assert frame["agent_id"] == agent_id
        assert frame["run_id"] is None
        assert "token" not in frame
        assert "content" not in frame
        assert "text" not in frame


@pytest.mark.asyncio
async def test_non_owner_does_not_receive_thread_changed(env: Any) -> None:
    c, srv, alice_auth, bob_auth, _admin = env
    agent_id = await _create_agent(c, alice_auth)

    async with _notifications_ws(c, bob_auth) as bob_ws:
        await bob_ws.send_json({"type": "ping"})
        assert await bob_ws.receive_json() == {"type": "pong"}
        resp = await c.post(f"/api/agents/{agent_id}/threads", headers=alice_auth)
        assert resp.status_code == 201, resp.text
        # Bob should not get alice's event; ping/pong still works.
        await bob_ws.send_json({"type": "ping"})
        assert await bob_ws.receive_json() == {"type": "pong"}


@pytest.mark.asyncio
async def test_emit_helper_fans_out_via_notifications_ws(env: Any) -> None:
    c, srv, alice_auth, bob_auth, _admin = env
    alice = srv.user_manager.get("alice")
    bob = srv.user_manager.get("bob")
    assert alice is not None and bob is not None

    async with (
        _notifications_ws(c, alice_auth) as alice_ws,
        _notifications_ws(c, bob_auth) as bob_ws,
    ):
        await alice_ws.send_json({"type": "ping"})
        await bob_ws.send_json({"type": "ping"})
        assert await alice_ws.receive_json() == {"type": "pong"}
        assert await bob_ws.receive_json() == {"type": "pong"}
        await srv.app_runtime.gateway.emit_thread_changed(
            owner_user_id=alice.id,
            agent_id="agent-x",
            thread_id="thr_x",
            reason="completed",
            run_id="run_1",
        )
        frame = await alice_ws.receive_json()
        assert frame["type"] == "thread.changed"
        assert frame["reason"] == "completed"
        assert frame["run_id"] == "run_1"
        await bob_ws.send_json({"type": "ping"})
        assert await bob_ws.receive_json() == {"type": "pong"}


@pytest.mark.asyncio
async def test_subscribe_turn_status_includes_schema_version(env: Any) -> None:
    c, srv, alice_auth, _bob, _admin = env
    agent_id = await _create_agent(c, alice_auth)
    resp = await c.post(f"/api/agents/{agent_id}/threads", headers=alice_auth)
    assert resp.status_code == 201
    tid = resp.json()["thread_id"]

    async with ws_connect(
        c._octop_app, f"/api/agents/{agent_id}/chat/ws?token={ws_token(alice_auth)}"
    ) as chat:
        await chat.send_json({"type": "subscribe", "thread_id": tid})
        status = await chat.receive_json()
        assert status["type"] == "turn_status"
        assert status["thread_id"] == tid
        assert status["active"] is False
        assert status["schema_version"] == 1
        assert status["input_controls"] is True
        # Idle with no live steering; may still carry last_event_at from created.
        runtime = status.get("runtime")
        assert runtime is None or (
            isinstance(runtime, dict)
            and runtime.get("phase") is None
            and "last_event_at" in runtime
        )
