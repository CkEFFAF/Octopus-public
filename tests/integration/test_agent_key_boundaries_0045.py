"""Machine credentials cannot inherit the issuing human's account permissions."""

from __future__ import annotations

from typing import Any

import pytest

from tests.support.auth import create_agent


@pytest.mark.asyncio
async def test_machine_credentials_cannot_access_account_management(
    env_with_provider: tuple[Any, Any, dict[str, str]],
) -> None:
    client, _server, human = env_with_provider
    expert = await create_agent(client, human)
    created = await client.post(
        "/api/auth/agent-access-keys",
        headers=human,
        json={"name": "restricted", "days": 1, "scopes": ["tasks.read"], "expert_ids": [expert]},
    )
    assert created.status_code == 201
    secret = created.json()["secret"]
    exchanged = await client.post("/api/auth/agent-access-keys/exchange", json={"secret": secret})
    assert exchanged.status_code == 200
    for credential in (secret, exchanged.json()["access_token"]):
        for path in ("/api/users", "/api/agents", "/api/providers"):
            response = await client.get(path, headers={"Authorization": f"Bearer {credential}"})
            assert response.status_code == 403, (path, response.status_code)
        for path in ("/api/task-board/actions", f"/api/agents/{expert}/chat/hitl/resume"):
            assert (
                await client.post(path, headers={"Authorization": f"Bearer {credential}"}, json={})
            ).status_code == 403


@pytest.mark.asyncio
async def test_machine_sessions_and_tasks_remain_credential_scoped(
    env_with_provider: tuple[Any, Any, dict[str, str]],
) -> None:
    client, server, human = env_with_provider
    expert = await create_agent(client, human)
    human_thread = (await client.post(f"/api/agents/{expert}/threads", headers=human)).json()[
        "thread_id"
    ]
    credentials = []
    for name in ("first", "second"):
        response = await client.post(
            "/api/auth/agent-access-keys",
            headers=human,
            json={
                "name": name,
                "days": 1,
                "scopes": ["tasks.create", "tasks.read"],
                "expert_ids": [expert],
            },
        )
        assert response.status_code == 201
        credentials.append({"Authorization": f"Bearer {response.json()['secret']}"})
    first, second = credentials
    created_thread = await client.post(f"/api/agents/{expert}/threads", headers=first)
    assert created_thread.status_code == 201
    thread_id = created_thread.json()["thread_id"]
    # Neither ordinary thread creation nor subsequent work may rebind the human chat.
    from octop.infra.gateway.threads import ThreadRegistry

    user_id = (await client.get("/api/auth/me", headers=human)).json()["id"]
    assert (
        server.app_runtime.gateway.thread_registry.get_bound_thread_id(
            ThreadRegistry.dashboard_key(agent_id=expert, user_id=user_id)
        )
        == human_thread
    )
    body = {
        "command_id": "one-command",
        "agent_id": expert,
        "origin_thread_id": thread_id,
        "title": "Scoped task",
        "instructions": "Compute a result",
    }
    for execution in (
        {"target_kind": "local"},
        {"device_id": "guessed-device"},
        {"working_dir": "guessed-directory"},
    ):
        assert (
            await client.post(
                "/api/work-items", headers=first, json={**body, "execution": execution}
            )
        ).status_code == 403
    forbidden_origin = await client.post(
        "/api/work-items", headers=first, json={**body, "origin_thread_id": human_thread}
    )
    assert forbidden_origin.status_code == 403
    created = await client.post("/api/work-items", headers=first, json=body)
    assert created.status_code == 200
    task_id = created.json()["task_id"]
    assert (await client.get(f"/api/work-items/{task_id}", headers=first)).status_code == 200
    assert (await client.get(f"/api/work-items/{task_id}", headers=second)).status_code == 403
    assert (
        await client.get(f"/api/agents/{expert}/threads/{thread_id}/history", headers=second)
    ).status_code == 403
    assert (await client.get("/api/work-items", headers=second)).json()["items"] == []
    replay = await client.post("/api/work-items", headers=first, json=body)
    assert replay.status_code == 200
    assert replay.json()["task_id"] == task_id


@pytest.mark.asyncio
async def test_machine_jwt_rechecks_live_scopes_and_expiry(env_with_provider):
    client, server, human = env_with_provider
    expert = await create_agent(client, human)
    minted = (
        await client.post(
            "/api/auth/agent-access-keys",
            headers=human,
            json={
                "name": "live-policy",
                "days": 1,
                "scopes": ["tasks.read"],
                "expert_ids": [expert],
            },
        )
    ).json()
    secret, key_id = minted["secret"], minted["key"]["key_id"]
    exchanged = (
        await client.post("/api/auth/agent-access-keys/exchange", json={"secret": secret})
    ).json()["access_token"]
    credentials = [{"Authorization": f"Bearer {token}"} for token in (secret, exchanged)]
    with server.services.db.transaction() as conn:
        conn.execute(
            "UPDATE agent_access_keys SET scopes_json = ? WHERE key_id = ?",
            ('["experts.read"]', key_id),
        )
    for headers in credentials:
        assert (await client.get("/api/work-items", headers=headers)).status_code == 403
        assert (
            await client.get("/api/auth/agent-access-keys/identity", headers=headers)
        ).status_code == 200
    with server.services.db.transaction() as conn:
        conn.execute("UPDATE agent_access_keys SET expires_at = 0 WHERE key_id = ?", (key_id,))
    for headers in credentials:
        assert (
            await client.get("/api/auth/agent-access-keys/identity", headers=headers)
        ).status_code == 401
    with server.services.db.transaction() as conn:
        conn.execute(
            "UPDATE agent_access_keys SET expires_at = ? WHERE key_id = ?", (9999999999, key_id)
        )
        conn.execute(
            "UPDATE users SET disabled = 1 WHERE id = ?", (minted["key"]["owner_user_id"],)
        )
    for headers in credentials:
        assert (
            await client.get("/api/auth/agent-access-keys/identity", headers=headers)
        ).status_code == 401


@pytest.mark.asyncio
async def test_shared_expert_unshare_removes_existing_access(env_alice_bob_agent):
    client, server, alice, bob, expert = env_alice_bob_agent
    with server.services.db.transaction() as conn:
        conn.execute("UPDATE agents SET is_shared = 1 WHERE agent_id = ?", (expert,))
    minted = await client.post(
        "/api/auth/agent-access-keys",
        headers=bob,
        json={
            "name": "shared",
            "days": 1,
            "scopes": ["tasks.read", "tasks.create"],
            "expert_ids": [expert],
        },
    )
    assert minted.status_code == 201
    machine = {"Authorization": f"Bearer {minted.json()['secret']}"}
    thread = (await client.post(f"/api/agents/{expert}/threads", headers=machine)).json()[
        "thread_id"
    ]
    created = await client.post(
        "/api/work-items",
        headers=machine,
        json={
            "command_id": "shared-task",
            "agent_id": expert,
            "origin_thread_id": thread,
            "title": "shared",
            "instructions": "read",
        },
    )
    assert created.status_code == 200
    task = created.json()["task_id"]
    with server.services.db.transaction() as conn:
        conn.execute("UPDATE agents SET is_shared = 0 WHERE agent_id = ?", (expert,))
    assert (await client.get(f"/api/work-items/{task}", headers=machine)).status_code == 403
    assert (
        await client.get(f"/api/agents/{expert}/threads/{thread}/history", headers=machine)
    ).status_code == 403
    assert (await client.get("/api/work-items?status_group=all", headers=machine)).json()[
        "items"
    ] == []
