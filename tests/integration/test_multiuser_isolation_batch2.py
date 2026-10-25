"""0038 Batch2: F06 JWT revoke + F07 desktop WS after disable."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.support.auth import TEST_PASSWORD, auth_header


@pytest.fixture
async def ordinary(env):
    client, server, admin = env
    created = await client.post(
        "/api/users",
        headers=admin,
        json={"username": "batch2-user", "password": TEST_PASSWORD, "permissions": []},
    )
    assert created.status_code == 201, created.text
    auth = await auth_header(client, username="batch2-user")
    return client, server, admin, auth, created.json()["id"]


@pytest.mark.parametrize(
    "operation", ["logout", "change-password", "reset-password", "disable-enable"]
)
async def test_old_session_is_invalidated_after_security_action(ordinary, operation):
    client, _, admin, auth, uid = ordinary
    if operation == "logout":
        result = await client.post("/api/auth/logout", headers=auth)
        assert result.status_code == 204
    elif operation == "change-password":
        result = await client.post(
            "/api/auth/change-password",
            headers=auth,
            json={"old_password": TEST_PASSWORD, "new_password": "ChangedPass12"},
        )
        assert result.status_code == 204, result.text
    elif operation == "reset-password":
        result = await client.post(
            f"/api/users/{uid}/reset-password",
            headers=admin,
            json={"new_password": "ChangedPass12"},
        )
        assert result.status_code == 204, result.text
    else:
        assert (
            await client.patch(f"/api/users/{uid}", headers=admin, json={"disabled": True})
        ).status_code == 200
        assert (await client.get("/api/auth/me", headers=auth)).status_code in (401, 403)
        assert (
            await client.patch(f"/api/users/{uid}", headers=admin, json={"disabled": False})
        ).status_code == 200
    replay = await client.get("/api/auth/me", headers=auth)
    assert replay.status_code in (401, 403), (
        f"Old JWT remains usable after {operation}: HTTP {replay.status_code}"
    )


async def test_fresh_login_works_after_logout(ordinary):
    client, _, _, auth, _ = ordinary
    assert (await client.post("/api/auth/logout", headers=auth)).status_code == 204
    fresh = await auth_header(client, username="batch2-user")
    me = await client.get("/api/auth/me", headers=fresh)
    assert me.status_code == 200
    assert me.json()["username"] == "batch2-user"


async def test_existing_desktop_socket_stops_after_user_disable(ordinary, monkeypatch):
    from starlette.websockets import WebSocket

    from octop.api.middleware.key_sessions import AccessKeyWebSocketMiddleware
    from octop.api.routers.desktop import stream

    client, server, admin, auth, uid = ordinary
    update = await client.patch(
        f"/api/users/{uid}", headers=admin, json={"permissions": ["desktop"]}
    )
    assert update.status_code == 200
    # Re-login so JWT carries desktop permission and a live sid.
    auth = await auth_header(client, username="batch2-user")
    token = auth["Authorization"].removeprefix("Bearer ")
    handler = AsyncMock()
    monkeypatch.setattr(
        stream,
        "desktop_status",
        lambda **_: SimpleNamespace(setup_state="ready", ok=True, display=None),
    )
    monkeypatch.setattr(stream, "acquire_session", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(stream, "release_session", AsyncMock())
    monkeypatch.setattr(stream, "supersede_user_stream", AsyncMock())
    monkeypatch.setattr(stream, "clear_user_stream", AsyncMock())
    monkeypatch.setattr(stream, "_stream_loop", AsyncMock())
    monkeypatch.setattr(stream, "_handle_input", handler)
    count = 0
    sent = []

    async def receive():
        nonlocal count
        count += 1
        if count == 1:
            return {"type": "websocket.connect"}
        if count == 2:
            return {
                "type": "websocket.receive",
                "text": json.dumps({"type": "start", "token": token}),
            }
        if count == 3:
            disabled = await client.patch(
                f"/api/users/{uid}", headers=admin, json={"disabled": True}
            )
            assert disabled.status_code == 200
            assert (await client.get("/api/auth/me", headers=auth)).status_code in (401, 403)
            return {
                "type": "websocket.receive",
                "text": json.dumps({"type": "click", "x": 1, "y": 1}),
            }
        return {"type": "websocket.receive", "text": json.dumps({"type": "stop"})}

    async def send(frame):
        sent.append(frame)

    async def endpoint(scope, receive, send):
        await stream.desktop_stream_ws(WebSocket(scope, receive, send), token=None)

    scope = {
        "type": "websocket",
        "path": "/api/desktop/stream",
        "headers": [],
        "query_string": b"",
        "app": SimpleNamespace(state=SimpleNamespace(octop_server=server)),
    }
    await AccessKeyWebSocketMiddleware(endpoint, server)(scope, receive, send)
    assert count >= 3, sent
    assert handler.await_count == 0, (
        f"Desktop input still dispatched after account disable: {handler.await_count}; {sent}"
    )
