"""Signed-in users never see or mutate another account's model credentials."""

import json

import pytest

from tests.support.auth import create_user


@pytest.mark.parametrize("prefix", ["/api/providers", "/api/admin/providers"])
async def test_provider_patch_preserves_omitted_fields_and_clears_explicit_null(env, prefix):
    client, server, admin_auth = env
    created = await client.post(
        "/api/providers",
        headers=admin_auth,
        json={
            "name": "nullable-patch",
            "kind": "openai",
            "base_url": "https://example.test/v1",
            "api_key": "disposable-test-key",
            "extra_json": '{"test":true}',
            "note": "original",
            "models": [{"id": "keep", "enabled": True}],
        },
    )
    assert created.status_code == 201
    provider_id = created.json()["id"]
    response = await client.patch(
        f"{prefix}/{provider_id}", headers=admin_auth, json={"note": "updated"}
    )
    assert response.status_code == 200
    assert response.json()["api_key"] == "disposable-test-key"
    assert response.json()["base_url"] == "https://example.test/v1"
    response = await client.patch(
        f"{prefix}/{provider_id}",
        headers=admin_auth,
        json={"note": None, "api_key": None, "base_url": None, "extra_json": None},
    )
    assert response.status_code == 200
    row = server.services.provider_repo.get_for_admin(provider_id)
    assert row.api_key is None
    assert row.note is None
    assert row.base_url is None
    assert row.extra_json is None
    assert row.kind == "openai"
    assert json.loads(row.models_json) == [{"id": "keep", "enabled": True}]


async def test_account_provider_crud_catalog_and_admin_management(env):
    client, server, admin_auth = env
    a_auth = await create_user(client, admin_auth, username="provider-a")
    b_auth = await create_user(client, admin_auth, username="provider-b")
    a_id = server.services.user_repo.get_by_username("provider-a").id
    b_id = server.services.user_repo.get_by_username("provider-b").id
    payload = {
        "name": "same",
        "kind": "openai",
        "base_url": "https://example.test/v1",
        "models": [{"id": "model-a", "enabled": True}],
    }
    first = await client.post(
        "/api/providers", headers=a_auth, json={**payload, "api_key": "secret-a"}
    )
    second = await client.post(
        "/api/providers",
        headers=b_auth,
        json={**payload, "api_key": "secret-b", "models": [{"id": "model-b", "enabled": True}]},
    )
    assert first.status_code == second.status_code == 201
    a_provider, b_provider = first.json()["id"], second.json()["id"]
    assert first.json()["user_id"] == a_id
    assert second.json()["user_id"] == b_id
    assert (await client.get("/api/providers", headers=a_auth)).json() == [first.json()]
    assert (await client.get("/api/providers", headers=b_auth)).json() == [second.json()]
    assert (await client.get("/api/providers/resolved", headers=b_auth)).json()[0][
        "model"
    ] == "model-b"
    for method in ("patch", "delete"):
        kwargs = {"json": {"api_key": "attack"}} if method == "patch" else {}
        response = await getattr(client, method)(
            f"/api/providers/{a_provider}", headers=b_auth, **kwargs
        )
        assert response.status_code == 404
    assert (
        await client.post(f"/api/providers/{a_provider}/test", headers=b_auth)
    ).status_code == 404
    assert (
        await client.post(
            "/api/providers", headers=b_auth, json={**payload, "name": "bad", "user_id": a_id}
        )
    ).status_code == 403
    assert (await client.post("/api/providers", headers=a_auth, json=payload)).status_code == 409
    assert (await client.get("/api/admin/providers", headers=b_auth)).status_code == 403
    admin_update = await client.patch(
        f"/api/admin/providers/{b_provider}", headers=admin_auth, json={"note": "managed"}
    )
    assert admin_update.status_code == 200
    assert server.services.provider_repo.get(a_id, a_provider).api_key == "secret-a"
    assert server.services.provider_repo.get(b_id, b_provider).note == "managed"
    assert (
        await client.put(
            "/api/providers/active-model",
            headers=a_auth,
            json={"provider_name": "same", "model": "model-a"},
        )
    ).status_code == 200
    assert (await client.get("/api/providers/active-model", headers=b_auth)).json() == {
        "provider_name": "",
        "model": "",
    }
    assert (
        await client.put(
            "/api/providers/active-model",
            headers=b_auth,
            json={"provider_name": "same", "model": "model-a"},
        )
    ).status_code == 400


async def test_shared_agent_uses_owner_catalog_without_exposing_owner_keys(env):
    client, server, admin_auth = env
    await create_user(client, admin_auth, username="model-owner")
    peer_auth = await create_user(client, admin_auth, username="model-peer")
    owner_id = server.services.user_repo.get_by_username("model-owner").id
    peer_id = server.services.user_repo.get_by_username("model-peer").id
    for uid, model in ((owner_id, "owner-model"), (peer_id, "peer-model")):
        server.services.provider_repo.create(
            user_id=uid,
            name="same",
            kind="openai",
            base_url="https://example.test/v1",
            api_key=f"private-{uid}",
            models_json=json.dumps([{"id": model, "enabled": True}]),
        )
    server.services.agent_repo.create(agent_id="shared-model", name="Shared", user_id=owner_id)
    server.services.settings_repo.set_active_model(owner_id, "same", "owner-model")
    scope = {**peer_auth, "X-Octop-Agent-Id": "shared-model"}
    assert (await client.get("/api/providers/resolved", headers=scope)).status_code == 403
    server.services.agent_repo.set_shared("shared-model", True)
    response = await client.get("/api/providers/resolved", headers=scope)
    assert response.status_code == 200
    assert [item["model"] for item in response.json()] == ["owner-model"]
    assert "api_key" not in response.text and "private-" not in response.text
    assert (await client.get("/api/providers/active-model", headers=scope)).json() == {
        "provider_name": "same",
        "model": "owner-model",
    }
    assert (await client.get("/api/providers", headers=scope)).json()[0]["user_id"] == peer_id


async def test_codex_oauth_state_and_logout_are_account_scoped(env):
    from octop.infra.agents.providers.codex_apply import apply_codex_credentials, codex_user_paths
    from octop.infra.agents.providers.codex_oauth import load_codex_token, save_codex_token

    client, server, admin_auth = env
    first_auth = await create_user(client, admin_auth, username="oauth-first")
    second_auth = await create_user(client, admin_auth, username="oauth-second")
    first_id = server.services.user_repo.get_by_username("oauth-first").id
    second_id = server.services.user_repo.get_by_username("oauth-second").id
    credentials = {
        "access": "first-token",
        "refresh": "first-refresh",
        "expires": 9999999999999,
        "account_id": "first-account",
    }
    services = server.services
    # A legacy token belongs only to the explicitly migrated account.
    save_codex_token(services.paths, credentials)
    services.settings_repo.set("providers.legacy_owner", str(first_id))
    second_paths = codex_user_paths(services, second_id)
    assert load_codex_token(second_paths) is None
    first_paths = codex_user_paths(services, first_id)
    assert load_codex_token(first_paths) == credentials
    assert load_codex_token(services.paths) is None
    first_provider = apply_codex_credentials(services, first_paths, credentials, user_id=first_id)
    second_credentials = {**credentials, "access": "second-token", "refresh": "second-refresh"}
    second_provider = apply_codex_credentials(
        services, second_paths, second_credentials, user_id=second_id
    )
    services.settings_repo.set(
        "codex_oauth.pending.first",
        json.dumps({"status": "ok", "provider_id": first_provider, "user_id": first_id}),
    )
    services.settings_repo.set("codex_oauth.pending.legacy", json.dumps({"status": "ok"}))
    assert (
        await client.get("/api/providers/codex-oauth/pending/first", headers=first_auth)
    ).status_code == 200
    assert (
        await client.get("/api/providers/codex-oauth/pending/first", headers=second_auth)
    ).status_code == 403
    assert (
        await client.get("/api/providers/codex-oauth/pending/legacy", headers=second_auth)
    ).status_code == 403
    assert (
        await client.delete("/api/providers/codex-oauth", headers=second_auth)
    ).status_code == 204
    assert load_codex_token(second_paths) is None
    assert load_codex_token(first_paths) == credentials
    assert services.provider_repo.get(first_id, first_provider).api_key == "first-token"
    assert services.provider_repo.get(second_id, second_provider).api_key == ""
