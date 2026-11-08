"""Account isolation and upstream contracts for dashboard plugins."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from octop.infra.plugins import marketplace
from octop.infra.plugins.marketplace import PluginMarketplace


async def test_catalog_install_config_and_uninstall_are_private(env_admin_alice: Any) -> None:
    client, srv, admin, alice = env_admin_alice
    catalogs = [await client.get("/api/plugins/catalog", headers=auth) for auth in (admin, alice)]
    assert all(result.status_code == 200 for result in catalogs)
    assert [row["id"] for row in catalogs[0].json()] == [row["id"] for row in catalogs[1].json()]
    assert not catalogs[1].json()[0]["installed"]

    installed = await client.put("/api/plugins/mine/cost-meter", headers=alice, json={})
    assert installed.status_code == 200
    key = "fixture-alice-private-key"
    saved = await client.patch(
        "/api/plugins/cost-meter/config",
        headers=alice,
        json={"go_api_key": key, "subscription_expires_at": "2026-12-08T12:30:00+08:00"},
    )
    assert saved.status_code == 200, saved.text
    assert key not in saved.text
    assert saved.json()["key_configured"]
    assert saved.json()["subscription_source"] == "manual"
    assert saved.headers["cache-control"] == "no-store"
    assert saved.json()["go"]["monthly"] is None
    admin_state = (await client.get("/api/plugins/cost-meter/state", headers=admin)).json()
    assert not admin_state["key_configured"]
    assert not admin_state["installation"]["installed"]
    assert admin_state["subscription_expires_at"] is None

    # A different user's uninstall cannot erase Alice's installation or key.
    assert (await client.delete("/api/plugins/mine/cost-meter", headers=admin)).status_code == 204
    assert (await client.get("/api/plugins/cost-meter/state", headers=alice)).json()[
        "key_configured"
    ]
    with srv.services.db.connect() as conn:
        stored = conn.execute(
            "SELECT value FROM settings WHERE key LIKE 'dashboard_plugins.%'"
        ).fetchall()
    assert all(key not in row["value"] for row in stored)
    assert (await client.delete("/api/plugins/mine/cost-meter", headers=alice)).status_code == 204
    reset = (await client.get("/api/plugins/cost-meter/state", headers=alice)).json()
    assert not reset["key_configured"]
    assert not reset["installation"]["installed"]


async def test_blank_key_preserves_and_clear_removes_it(env: Any) -> None:
    client, _srv, auth = env
    await client.put("/api/plugins/mine/cost-meter", headers=auth, json={})
    await client.patch(
        "/api/plugins/cost-meter/config", headers=auth, json={"go_api_key": "fixture-key"}
    )
    kept = await client.patch(
        "/api/plugins/cost-meter/config", headers=auth, json={"go_api_key": ""}
    )
    assert kept.json()["key_configured"]
    bad = await client.patch(
        "/api/plugins/cost-meter/config",
        headers=auth,
        json={"subscription_expires_at": "2026-12-01T00:00:00"},
    )
    assert bad.status_code == 422
    cleared = await client.patch(
        "/api/plugins/cost-meter/config", headers=auth, json={"clear_go_api_key": True}
    )
    assert not cleared.json()["key_configured"]


async def test_auth_and_catalog_allowlist(env: Any) -> None:
    client, _srv, auth = env
    for path in ("/api/plugins/catalog", "/api/plugins/cost-meter/state"):
        assert (await client.get(path)).status_code == 401
    assert (
        await client.put("/api/plugins/mine/not-in-catalog", headers=auth, json={})
    ).status_code == 404
    assert (
        await client.patch("/api/plugins/cost-meter/config", headers=auth, json={})
    ).status_code == 404


async def test_official_quota_cache_and_stale_error(
    env_admin_alice: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, srv, admin, alice = env_admin_alice
    for auth in (admin, alice):
        await client.put("/api/plugins/mine/cost-meter", headers=auth, json={})
        await client.patch(
            "/api/plugins/cost-meter/config",
            headers=auth,
            json={"go_api_key": "Bearer fixture-private-key"},
        )
    calls: list[httpx.Request] = []
    mode = "ok"

    def upstream(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert str(request.url) == marketplace.GO_USAGE_URL
        assert request.headers["authorization"] == "Bearer fixture-private-key"
        if mode == "error":
            return httpx.Response(401, json={"message": "fixture-private-key"})
        return httpx.Response(
            200,
            json={
                "usage": {
                    "rolling": {"percent": 17, "resetsAt": "2026-11-09T01:00:00Z"},
                    "weekly": {"percent": 42},
                    "monthly": {"percent": 65},
                }
            },
        )

    actual_client = httpx.AsyncClient
    monkeypatch.setattr(
        marketplace.httpx,
        "AsyncClient",
        lambda **kwargs: actual_client(transport=httpx.MockTransport(upstream), **kwargs),
    )
    result = await client.post("/api/plugins/cost-meter/refresh", headers=alice)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["go"]["rolling"]["percent"] == 17
    assert body["go"]["weekly"]["percent"] == 42
    assert body["go"]["monthly"]["percent"] == 65
    assert body["subscription_expires_at"] is None
    assert "fixture-private-key" not in result.text
    await client.post("/api/plugins/cost-meter/refresh", headers=alice)
    assert len(calls) == 1
    await client.post("/api/plugins/cost-meter/refresh", headers=admin)
    assert len(calls) == 2, "one user's cooldown must not suppress another's refresh"

    market = PluginMarketplace(srv.services)
    alice_id = (await client.get("/api/auth/me", headers=alice)).json()["id"]
    raw, record = market._record(alice_id)
    record["quota"]["attempted_at"] = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
    assert market._replace(alice_id, "cost-meter", raw, record)
    mode = "error"
    stale = await client.post("/api/plugins/cost-meter/refresh", headers=alice)
    assert stale.json()["go"]["status"] == "error"
    assert stale.json()["go"]["error_code"] == "auth_failed"
    assert stale.json()["go"]["monthly"]["percent"] == 65
    assert "fixture-private-key" not in stale.text
    assert len(calls) == 3
    # Turning off the plugin stops quota calls without deleting its settings.
    await client.put("/api/plugins/mine/cost-meter", headers=alice, json={"enabled": False})
    await client.post("/api/plugins/cost-meter/refresh", headers=alice)
    assert len(calls) == 3


@pytest.mark.parametrize(
    "payload",
    [
        {"usage": {"rolling": {"percent": None}}},
        {"usage": {"monthly": {"percent": False}}},
        {"error": "fixture-key"},
    ],
)
async def test_missing_quota_is_never_reported_as_zero(
    env: Any, monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> None:
    client, _srv, auth = env
    await client.put("/api/plugins/mine/cost-meter", headers=auth, json={})
    await client.patch(
        "/api/plugins/cost-meter/config", headers=auth, json={"go_api_key": "fixture-key"}
    )
    actual_client = httpx.AsyncClient
    monkeypatch.setattr(
        marketplace.httpx,
        "AsyncClient",
        lambda **kwargs: actual_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
            **kwargs,
        ),
    )
    response = await client.post("/api/plugins/cost-meter/refresh", headers=auth)
    assert response.status_code == 200
    assert response.json()["go"]["status"] == "error"
    assert response.json()["go"]["rolling"] is None
    assert response.json()["go"]["monthly"] is None
    assert "fixture-key" not in json.dumps(response.json())


@pytest.mark.parametrize(
    "value",
    ["fixture-secret-" + "x" * 4096, ["fixture-secret-input"], {"key": "fixture-secret-input"}],
)
async def test_invalid_key_input_is_redacted(env: Any, value: object) -> None:
    client, _srv, auth = env
    response = await client.patch(
        "/api/plugins/cost-meter/config", headers=auth, json={"go_api_key": value}
    )
    assert response.status_code == 422
    assert "fixture-secret" not in response.text
    assert all("input" not in error and "ctx" not in error for error in response.json()["detail"])
    assert response.headers["cache-control"] == "no-store"


async def test_configure_cannot_restore_uninstalled_credentials(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, srv, auth = env
    await client.put("/api/plugins/mine/cost-meter", headers=auth, json={})
    user_id = (await client.get("/api/auth/me", headers=auth)).json()["id"]
    market = PluginMarketplace(srv.services)
    encrypt = marketplace.encrypt_credentials

    def uninstall_while_encrypting(repo: Any, payload: Any) -> bytes:
        encrypted = encrypt(repo, payload)
        market.uninstall(user_id, "cost-meter")
        return encrypted

    monkeypatch.setattr(marketplace, "encrypt_credentials", uninstall_while_encrypting)
    response = await client.patch(
        "/api/plugins/cost-meter/config", headers=auth, json={"go_api_key": "fixture-secret-input"}
    )
    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    state = (await client.get("/api/plugins/cost-meter/state", headers=auth)).json()
    assert not state["installation"]["installed"] and not state["key_configured"]
    assert market._record(user_id)[0] is None


async def test_refresh_cannot_write_after_uninstall(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, srv, auth = env
    await client.put("/api/plugins/mine/cost-meter", headers=auth, json={})
    await client.patch(
        "/api/plugins/cost-meter/config", headers=auth, json={"go_api_key": "fixture-key"}
    )
    user_id = (await client.get("/api/auth/me", headers=auth)).json()["id"]
    market = PluginMarketplace(srv.services)
    actual_client = httpx.AsyncClient

    def upstream(request: httpx.Request) -> httpx.Response:
        market.uninstall(user_id, "cost-meter")
        return httpx.Response(200, json={"usage": {"rolling": {"percent": 99}}})

    monkeypatch.setattr(
        marketplace.httpx,
        "AsyncClient",
        lambda **kwargs: actual_client(transport=httpx.MockTransport(upstream), **kwargs),
    )
    response = await client.post("/api/plugins/cost-meter/refresh", headers=auth)
    assert response.status_code == 200
    assert not response.json()["installation"]["installed"]
    assert not response.json()["key_configured"]
    assert response.json()["go"]["rolling"] is None
    assert market._record(user_id)[0] is None
