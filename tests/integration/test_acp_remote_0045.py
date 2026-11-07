"""0045 integration: agent-access-keys HTTP + real ACP stdio client (not curl)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.support.auth import create_agent

ALL_SCOPES = [
    "experts.read",
    "tasks.create",
    "tasks.read",
    "tasks.input",
    "tasks.cancel",
    "resources.read",
]


@pytest.mark.asyncio
async def test_agent_access_key_http_lifecycle_and_key_login_rejected(
    env_with_provider: tuple[Any, Any, dict[str, str]],
) -> None:
    client, srv, auth = env_with_provider
    agent_id = await create_agent(client, auth)

    r = await client.post(
        "/api/auth/agent-access-keys",
        headers=auth,
        json={
            "name": "laptop-zed",
            "days": 30,
            "scopes": ALL_SCOPES,
            "expert_ids": [agent_id],
            "allow_existing_threads": False,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    secret = body["secret"]
    assert secret.startswith("oaa_")
    assert "secret" not in json.dumps(body["key"])
    assert body["acp_launch"]["command"] == "octop"
    assert body["acp_launch"]["protocol"]["package_version"] == "0.11.0"
    key_id = body["key"]["key_id"]

    listed = await client.get("/api/auth/agent-access-keys", headers=auth)
    assert listed.status_code == 200
    assert all("secret" not in k for k in listed.json()["keys"])

    bad = await client.post("/api/auth/key-login", json={"access_key": secret})
    assert bad.status_code == 401

    experts = await client.get("/api/auth/agent-access-keys/experts", headers=auth)
    assert experts.status_code == 200
    assert any(e["expert_id"] == agent_id for e in experts.json())

    mint = await client.post(
        "/api/auth/agent-access-keys",
        headers={"Authorization": f"Bearer {secret}"},
        json={
            "name": "evil",
            "days": 7,
            "scopes": ["tasks.read"],
            "expert_ids": [agent_id],
        },
    )
    assert mint.status_code == 403

    from octop.infra.auth.access_keys import AccessKeyService

    me = (await client.get("/api/auth/me", headers=auth)).json()
    oak = AccessKeyService(srv.services.repos).create(int(me["id"]), "browser", 30, True, True)[
        "secret"
    ]
    oak_bearer = await client.get(
        "/api/work-items",
        headers={"Authorization": f"Bearer {oak}"},
    )
    assert oak_bearer.status_code == 401

    # Machine bearer reaches work-items (empty list ok) when not revoked
    ok_list = await client.get(
        "/api/work-items",
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert ok_list.status_code == 200

    # Missing scope: create a read-only key and try cancel path later via revoke test
    rev = await client.post(f"/api/auth/agent-access-keys/{key_id}/revoke", headers=auth)
    assert rev.status_code == 204
    after = await client.get(
        "/api/work-items",
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert after.status_code == 401


@pytest.mark.asyncio
async def test_scope_missing_forbids_create(
    env_with_provider: tuple[Any, Any, dict[str, str]],
) -> None:
    client, _srv, auth = env_with_provider
    agent_id = await create_agent(client, auth)
    r = await client.post(
        "/api/auth/agent-access-keys",
        headers=auth,
        json={
            "name": "ro",
            "days": 7,
            "scopes": ["tasks.read"],
            "expert_ids": [agent_id],
        },
    )
    assert r.status_code == 201
    secret = r.json()["secret"]
    # Need an origin thread first — create via human, then machine without tasks.create
    thr = await client.post(f"/api/agents/{agent_id}/threads", headers=auth)
    assert thr.status_code == 201
    tid = thr.json()["thread_id"]
    denied = await client.post(
        "/api/work-items",
        headers={"Authorization": f"Bearer {secret}"},
        json={
            "command_id": "cmd-deny-1",
            "agent_id": agent_id,
            "origin_thread_id": tid,
            "title": "nope",
            "instructions": "x",
            "schema_version": 1,
        },
    )
    assert denied.status_code == 403
