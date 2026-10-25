"""Login/enrollment scopes, key-session revocation and account ownership."""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from octop.api.deps import maybe_sliding_renew_token, resolve_user_from_token
from octop.api.middleware.jwt_auth import install
from octop.api.middleware.key_sessions import AccessKeyWebSocketMiddleware
from octop.api.routers.auth import router as auth_router
from octop.api.routers.devices import router as device_router
from octop.infra.auth.tokens import decode_token, sign_token
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.devices.service import DeviceService
from octop.infra.errors import OctopError
from octop.infra.users.identity import User


@pytest.fixture
def rig(tmp_path: Path) -> Any:
    pool = SqlitePool(tmp_path / "keys.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="owner", role="admin", password_hash="unused")
    other = repos.user_repo.create(username="other", role="user", password_hash="unused")
    service = DeviceService(repos)
    secret = b"isolated-key-login-test-secret-at-least-32-bytes"
    repos.secret_repo.get_or_create("jwt", lambda: secret)

    def user(user_id: int) -> User | None:
        row = repos.user_repo.get(user_id)
        return (
            User(row.id, row.username, row.role, row.display_name)
            if row and not row.disabled
            else None
        )

    def mint_browser_token(
        user_id: int, uname: str, role: str, *, ttl_seconds: int = 3600
    ) -> str:
        sid = secrets.token_urlsafe(16)
        row = repos.user_repo.get(user_id)
        assert row is not None
        av = int(row.auth_version)
        repos.browser_session_repo.create(
            sid=sid,
            user_id=user_id,
            absolute_expires_at=time.time() + ttl_seconds,
            auth_version_at_issue=av,
        )
        return sign_token(
            secret,
            sub=user_id,
            uname=uname,
            role=role,
            ttl_seconds=ttl_seconds,
            sid=sid,
            av=av,
        )

    server = SimpleNamespace(
        _started=True,
        services=SimpleNamespace(
            secret_repo=repos.secret_repo,
            config=SimpleNamespace(access_token_ttl_seconds=3600),
            user_repo=repos.user_repo,
            repos=repos,
            db=pool,
        ),
        user_manager=SimpleNamespace(get_by_id=user),
        app_runtime=SimpleNamespace(devices=service),
    )
    app = FastAPI()
    app.state.octop_server = server
    app.include_router(auth_router, prefix="/api/auth")
    app.include_router(device_router, prefix="/api")
    install(app, server)

    @app.exception_handler(OctopError)
    async def handle(request: Request, exc: OctopError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.to_envelope())

    yield SimpleNamespace(
        pool=pool,
        repos=repos,
        owner=owner,
        other=other,
        service=service,
        keys=service.access_keys,
        secret=secret,
        server=server,
        app=app,
        mint_browser_token=mint_browser_token,
    )
    pool.close()


@pytest.mark.asyncio
async def test_key_login_renewal_revoke_and_delegation_denial(rig: Any) -> None:
    token = rig.mint_browser_token(rig.owner, "owner", "admin")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=rig.app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as http:
        made = await http.post("/api/auth/access-keys", json={"name": "Phone", "days": 30})
        assert made.status_code == 201
        key = made.json()
        listing = (await http.get("/api/auth/access-keys")).json()
        assert key["secret"] not in json.dumps(listing)
        assert "secret_hash" not in json.dumps(listing)
        # Another account cannot revoke or list this key.
        other = rig.mint_browser_token(rig.other, "other", "user")
        assert (
            await http.get("/api/auth/access-keys", headers={"Authorization": f"Bearer {other}"})
        ).json()["keys"] == []
        assert (
            await http.post(
                f"/api/auth/access-keys/{key['key']['key_id']}/revoke",
                headers={"Authorization": f"Bearer {other}"},
            )
        ).status_code == 404
        login = await http.post("/api/auth/key-login", json={"access_key": key["secret"]})
        assert login.status_code == 200
        browser_token = login.json()["access_token"]
        assert browser_token != key["secret"]
        payload = decode_token(rig.secret, browser_token)
        assert payload["sub"] == rig.owner
        assert payload["auth_key_id"] == key["key"]["key_id"]
        headers = {"Authorization": f"Bearer {browser_token}"}
        assert (await http.get("/api/devices", headers=headers)).status_code == 200
        assert (
            await http.post("/api/auth/access-keys", headers=headers, json={"name": "delegated"})
        ).status_code == 403
        assert (await http.post("/api/devices/pairing", headers=headers)).status_code == 403
        aging = sign_token(
            rig.secret,
            sub=rig.owner,
            uname="owner",
            role="admin",
            ttl_seconds=10,
            auth_key_id=key["key"]["key_id"],
        )
        renewed = maybe_sliding_renew_token(
            rig.server, aging, rig.server.user_manager.get_by_id(rig.owner)
        )
        assert renewed and decode_token(rig.secret, renewed)["auth_key_id"] == key["key"]["key_id"]
        await http.post(f"/api/auth/access-keys/{key['key']['key_id']}/revoke")
        assert (await http.get("/api/devices", headers=headers)).status_code == 401
        assert (
            await http.post("/api/auth/key-login", json={"access_key": key["secret"]})
        ).status_code == 401
        with pytest.raises(OctopError):
            resolve_user_from_token(rig.server, renewed)


@pytest.mark.parametrize("scope", ["browser", "devices"])
def test_key_scopes_expiry_and_disabled_account(rig: Any, scope: str) -> None:
    created = rig.keys.create(rig.owner, "Scoped", 1, scope == "browser", scope == "devices")
    assert rig.keys.authenticate(created["secret"], scope, "test")["owner_user_id"] == rig.owner
    other_scope = "devices" if scope == "browser" else "browser"
    with pytest.raises(OctopError):
        rig.keys.authenticate(created["secret"], other_scope, "test")
    with rig.pool.transaction() as conn:
        conn.execute("UPDATE account_access_keys SET expires_at = ?", (time.time() - 1,))
    with pytest.raises(OctopError):
        rig.keys.authenticate(created["secret"], scope, "test")
    active = rig.keys.create(rig.owner, "Active", 1, True, True)
    with rig.pool.transaction() as conn:
        conn.execute("UPDATE users SET disabled = 1 WHERE id = ?", (rig.owner,))
    with pytest.raises(OctopError):
        rig.keys.authenticate(active["secret"], scope, "test")


def test_key_survives_service_restart_without_persisting_plaintext(rig: Any) -> None:
    made = rig.keys.create(rig.owner, "Laptop", 30, False, True)
    fresh = DeviceService(rig.repos)
    first = fresh.enroll(
        access_key=made["secret"],
        name="first",
        platform="windows",
        capabilities=[],
        permissions=[],
        roots=[],
    )
    second = fresh.enroll(
        access_key=made["secret"],
        name="second",
        platform="linux",
        capabilities=[],
        permissions=[],
        roots=[],
    )
    assert first["device"]["device_id"] != second["device"]["device_id"]
    assert len(fresh.list_devices(rig.owner)) == 2
    stored = rig.repos.access_key_repo.get(made["key"]["key_id"])
    assert made["secret"] not in json.dumps(stored)
    fresh.access_keys.revoke(rig.owner, made["key"]["key_id"])
    with pytest.raises(OctopError):
        fresh.enroll(
            access_key=made["secret"],
            name="denied",
            platform="windows",
            capabilities=[],
            permissions=[],
            roots=[],
        )
    assert fresh.authenticate(first["device"]["device_id"], first["device_token"])


def test_invalid_keys_are_throttled_without_persisting_secrets(rig: Any) -> None:
    for _ in range(5):
        with pytest.raises(OctopError):
            rig.keys.authenticate("oak_invalid", "browser", "source")
    with pytest.raises(OctopError) as blocked:
        rig.keys.authenticate("oak_invalid", "browser", "source")
    assert blocked.value.status == 429


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["query", "start-frame"])
async def test_idle_browser_socket_closes_when_its_key_is_revoked(rig: Any, transport: str) -> None:
    made = rig.keys.create(rig.owner, "Socket", 1, True, False)
    token = sign_token(
        rig.secret, sub=rig.owner, uname="owner", role="admin", auth_key_id=made["key"]["key_id"]
    )
    messages: list[dict[str, Any]] = []
    accepted = asyncio.Event()
    first_frame = transport == "start-frame"

    async def send(message: Any) -> None:
        messages.append(message)

    async def receive() -> Any:
        nonlocal first_frame
        if first_frame:
            first_frame = False
            return {
                "type": "websocket.receive",
                "text": json.dumps({"type": "start", "token": token}),
            }
        await asyncio.Event().wait()

    async def endpoint(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "websocket.accept"})
        if transport == "start-frame":
            assert (await receive())["type"] == "websocket.receive"
        accepted.set()
        assert (await receive())["type"] == "websocket.disconnect"
        await send({"type": "websocket.close", "code": 1000})

    guard = AccessKeyWebSocketMiddleware(endpoint, rig.server)
    task = asyncio.create_task(
        guard(
            {
                "type": "websocket",
                "query_string": f"token={token}".encode() if transport == "query" else b"",
            },
            receive,
            send,
        )
    )
    await asyncio.wait_for(accepted.wait(), timeout=1)
    rig.keys.revoke(rig.owner, made["key"]["key_id"])
    await asyncio.wait_for(task, timeout=2)
    assert [m["code"] for m in messages if m["type"] == "websocket.close"] == [4001]
