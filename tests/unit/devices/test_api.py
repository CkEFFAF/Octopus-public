"""Real HTTP/JWT and outbound WebSocket client integration on an isolated server."""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from octop.api.middleware.jwt_auth import install
from octop.api.routers.devices import router
from octop.infra.auth.tokens import sign_token
from tests.support.browser_sessions import mint_browser_token
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.devices.client import DeviceClient
from octop.infra.devices.executor import DeviceExecutor
from octop.infra.devices.service import DeviceService
from octop.infra.errors import OctopError


@pytest.mark.asyncio
async def test_same_account_outbound_clients_http_auth_and_revoke(tmp_path: Path) -> None:
    pool = SqlitePool(tmp_path / "api.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="one-account", role="admin", password_hash="unused")
    other = repos.user_repo.create(
        username="different-account", role="user", password_hash="unused"
    )
    service = DeviceService(repos)
    secret = b"isolated-test-jwt-secret-do-not-use-in-product"
    server = SimpleNamespace(
        _started=True,
        app_runtime=SimpleNamespace(devices=service),
        services=SimpleNamespace(
            secret_repo=SimpleNamespace(get=lambda key: secret),
            config=SimpleNamespace(access_token_ttl_seconds=86400),
            user_repo=repos.user_repo,
            repos=repos,
            db=pool,
        ),
        user_manager=SimpleNamespace(get_by_id=repos.user_repo.get),
    )
    app = FastAPI()
    app.state.octop_server = server
    app.include_router(router, prefix="/api")
    install(app, server)

    @app.exception_handler(OctopError)
    async def error_handler(request: Request, exc: OctopError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.to_envelope())

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.listen(128)
    host = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    serve = asyncio.create_task(host.serve(sockets=[listener]))
    tasks: list[asyncio.Task[None]] = []
    clients: list[DeviceClient] = []
    try:
        for _ in range(100):
            if host.started:
                break
            await asyncio.sleep(0.02)
        assert host.started
        url = f"http://127.0.0.1:{port}"
        token = mint_browser_token(
            secret=secret, repos=repos, user_id=owner, username="one-account", role="admin"
        )
        headers = {"Authorization": f"Bearer {token}"}
        other_token = mint_browser_token(
            secret=secret,
            repos=repos,
            user_id=other,
            username="different-account",
            role="user",
        )
        async with httpx.AsyncClient(base_url=url, headers=headers) as http:
            reusable_key = service.access_keys.create(owner, "Second PC", 30, True, True)["secret"]
            assert (
                await http.get("/api/devices", headers={"Authorization": "Bearer invalid"})
            ).status_code == 401
            for index in range(2):
                shared = tmp_path / f"shared-{index}"
                shared.mkdir()
                if index == 0:
                    (shared / "hello.txt").write_text("real outbound device file", encoding="utf-8")
                roots = [
                    {
                        "id": "share",
                        "name": "Share",
                        "path": str(shared),
                        "read": True,
                        "write": True,
                    }
                ]
                executor = DeviceExecutor(
                    ["files_read", "files_write"], roots, state_dir=tmp_path / f"state-{index}"
                )
                client = DeviceClient(tmp_path / f"state-{index}")
                pairing = (await http.post("/api/devices/pairing")).json()
                await client.enroll(
                    url,
                    pairing["pairing_code"] if index == 0 else "",
                    f"PC-{index}",
                    executor,
                    access_key=reusable_key if index == 1 else None,
                )
                assert reusable_key not in json.dumps(client.load_state())
                clients.append(client)
                tasks.append(asyncio.create_task(client.run(executor)))
            for _ in range(100):
                devices = (await http.get("/api/devices")).json()["devices"]
                if len(devices) == 2 and all(d["online"] for d in devices):
                    break
                await asyncio.sleep(0.02)
            assert len(devices) == 2 and all(d["online"] for d in devices)
            source_id = next(d["device_id"] for d in devices if d["name"] == "PC-0")
            target_id = next(d["device_id"] for d in devices if d["name"] == "PC-1")
            result = await http.post(
                "/api/devices/transfers",
                json={
                    "source_device_id": source_id,
                    "source_root_id": "share",
                    "source_path": "hello.txt",
                    "target_device_id": target_id,
                    "target_root_id": "share",
                    "target_path": "received.txt",
                },
            )
            assert result.status_code == 202, result.text
            operation_id = result.json()["operation_id"]
            for _ in range(100):
                op = (await http.get(f"/api/devices/operations/{operation_id}")).json()
                if op["status"] not in {"queued", "running"}:
                    break
                await asyncio.sleep(0.02)
            assert op["status"] == "completed", op
            assert (
                tmp_path / "shared-1" / "received.txt"
            ).read_text() == "real outbound device file"
            response = await http.get(
                f"/api/devices/operations/{operation_id}",
                headers={"Authorization": f"Bearer {other_token}"},
            )
            assert response.status_code == 404
            state = clients[0].load_state()
            assert (
                await http.get(
                    "/api/devices", headers={"Authorization": f"Bearer {state['device_token']}"}
                )
            ).status_code == 401
            assert (await http.post(f"/api/devices/{source_id}/revoke")).status_code == 200
            response = await http.post(
                f"/api/devices/{source_id}/call", json={"action": "status", "params": {}}
            )
            assert response.status_code == 403
    finally:
        for client in clients:
            await client.stop()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await service.shutdown()
        host.should_exit = True
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(serve, 5)
        listener.close()
        pool.close()


@pytest.mark.asyncio
async def test_account_bearer_enroll_lists_under_owner(tmp_path: Path) -> None:
    """0004 AE-01/AE-02: password-session JWT enrolls; browser JWT alone is not enough without enroll call."""
    pool = SqlitePool(tmp_path / "api-account.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="owner", role="admin", password_hash="unused")
    other = repos.user_repo.create(username="other", role="user", password_hash="unused")
    service = DeviceService(repos)
    secret = b"isolated-test-jwt-secret-account-enroll"
    server = SimpleNamespace(
        _started=True,
        app_runtime=SimpleNamespace(devices=service),
        services=SimpleNamespace(
            secret_repo=SimpleNamespace(get=lambda key: secret),
            config=SimpleNamespace(access_token_ttl_seconds=86400),
            user_repo=repos.user_repo,
            repos=repos,
            db=pool,
        ),
        user_manager=SimpleNamespace(get_by_id=repos.user_repo.get),
    )
    app = FastAPI()
    app.state.octop_server = server
    app.include_router(router, prefix="/api")
    install(app, server)

    @app.exception_handler(OctopError)
    async def error_handler(request: Request, exc: OctopError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.to_envelope())

    transport = httpx.ASGITransport(app=app)
    token = mint_browser_token(
        secret=secret, repos=repos, user_id=owner, username="owner", role="admin"
    )
    other_token = mint_browser_token(
        secret=secret, repos=repos, user_id=other, username="other", role="user"
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        # AE-02: listing with JWT does not create a device.
        listed = await http.get("/api/devices", headers={"Authorization": f"Bearer {token}"})
        assert listed.status_code == 200
        assert listed.json()["devices"] == []
        # AE-01: explicit enroll with Bearer creates under owner.
        enrolled = await http.post(
            "/api/devices/enroll",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "Laptop",
                "platform": "windows",
                "capabilities": [],
                "permissions": [],
                "roots": [],
            },
        )
        assert enrolled.status_code == 201, enrolled.text
        body = enrolled.json()
        assert body["device_token"].startswith("odv_")
        assert "token_hash" not in str(body)
        devices = (
            await http.get("/api/devices", headers={"Authorization": f"Bearer {token}"})
        ).json()["devices"]
        assert len(devices) == 1 and devices[0]["name"] == "Laptop"
        other_list = (
            await http.get("/api/devices", headers={"Authorization": f"Bearer {other_token}"})
        ).json()["devices"]
        assert other_list == []
        # Mixing Bearer with pairing_code is rejected.
        pairing = (
            await http.post("/api/devices/pairing", headers={"Authorization": f"Bearer {token}"})
        ).json()
        mixed = await http.post(
            "/api/devices/enroll",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "pairing_code": pairing["pairing_code"],
                "name": "Mixed",
                "platform": "windows",
                "capabilities": [],
                "permissions": [],
                "roots": [],
            },
        )
        assert mixed.status_code == 401
        # Key-session JWT cannot enroll (use access_key instead).
        key = service.access_keys.create(owner, "browser", 30, True, True)
        key_token = sign_token(
            secret, sub=owner, uname="owner", role="admin", auth_key_id=key["key"]["key_id"]
        )
        rejected = await http.post(
            "/api/devices/enroll",
            headers={"Authorization": f"Bearer {key_token}"},
            json={
                "name": "FromKeySession",
                "platform": "windows",
                "capabilities": [],
                "permissions": [],
                "roots": [],
            },
        )
        assert rejected.status_code == 403
    pool.close()
