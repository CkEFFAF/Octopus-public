"""Machine provenance uses direct scoped credentials and survives revocation."""

from __future__ import annotations

from tests.support.auth import create_agent


async def test_machine_identity_is_server_owned_and_categories_precede_limit(
    env_with_provider, monkeypatch
):
    client, server, human = env_with_provider
    expert = await create_agent(client, human)
    ordinary = (await client.post(f"/api/agents/{expert}/threads", headers=human)).json()[
        "thread_id"
    ]
    server.services.thread_repo.set_pinned(ordinary, True)
    minted = (
        await client.post(
            "/api/auth/agent-access-keys",
            headers=human,
            json={
                "name": "Codex",
                "days": 1,
                "scopes": ["tasks.create", "tasks.read", "tasks.input"],
                "expert_ids": [expert],
            },
        )
    ).json()
    key_id = minted["key"]["key_id"]
    machine = {
        "Authorization": f"Bearer {minted['secret']}",
        "X-Sender-Name": "Owner impersonation",
    }
    remote = await client.post(
        f"/api/agents/{expert}/threads",
        headers=machine,
        json={"sender": {"kind": "human", "name": "Owner"}},
    )
    assert remote.status_code == 201
    tid = remote.json()["thread_id"]
    expected = {"kind": "machine", "id": key_id, "name": "Codex"}
    threads = (
        await client.get(
            f"/api/agents/{expert}/threads?limit=1&category=agent_collaboration", headers=human
        )
    ).json()
    assert len(threads) == 1 and threads[0]["thread_id"] == tid
    assert threads[0]["actor"] == expected
    server.app_runtime.gateway.ws_hub.mark_turn_active(tid)
    active = (
        await client.get(
            f"/api/agents/{expert}/sidebar-status?category=agent_collaboration", headers=human
        )
    ).json()
    assert active["working_threads"][0]["actor"] == expected
    assert not (
        await client.get(f"/api/agents/{expert}/sidebar-status?category=user", headers=human)
    ).json()["working_threads"]
    server.app_runtime.gateway.ws_hub.mark_turn_idle(tid)
    users = (
        await client.get(f"/api/agents/{expert}/threads?limit=1&category=user", headers=human)
    ).json()
    assert users[0]["thread_id"] == ordinary and "actor" not in users[0]
    # Attribution never broadens the existing machine route surface.
    assert (
        await client.get(
            f"/api/agents/{expert}/threads?category=agent_collaboration", headers=machine
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/agents/{expert}/threads/{ordinary}/inputs", headers=machine, json={}
        )
    ).status_code == 403
    monkeypatch.setattr(server.app_runtime.work_items, "_schedule_dispatch", lambda *_: None)
    body = {
        "command_id": "trusted-create",
        "agent_id": expert,
        "origin_thread_id": tid,
        "title": "Actual request",
        "instructions": "No model call",
    }
    assert (
        await client.post(
            "/api/work-items",
            headers=machine,
            json={**body, "sender": {"kind": "expert", "id": "spoof", "name": "Spoof"}},
        )
    ).status_code == 422
    created = await client.post("/api/work-items", headers=machine, json=body)
    assert created.status_code == 200
    task = created.json()["task_id"]
    event = server.services.repos.run_event_repo.get(
        minted["key"]["owner_user_id"], f"work:{task}:created"
    )
    assert event["payload"]["sender"] == expected
    assert (
        await client.post(
            f"/api/work-items/{task}/inputs",
            headers=machine,
            json={
                "command_id": "spoof-input",
                "text": "hello",
                "sender": {"kind": "machine", "id": "spoof", "name": "Spoof"},
            },
        )
    ).status_code == 422
    assert (
        await client.post(f"/api/auth/agent-access-keys/{key_id}/revoke", headers=human)
    ).status_code == 204
    history = await client.get(f"/api/agents/{expert}/threads/{tid}/history", headers=human)
    assert history.status_code == 200
    assert history.json()["actor"] == expected
    assert history.json()["category"] == "agent_collaboration"
    assert (
        await client.get(f"/api/agents/{expert}/threads/{tid}/history", headers=machine)
    ).status_code == 401
