from __future__ import annotations

import json

import pytest

from tests.support.auth import create_user


@pytest.mark.asyncio
async def test_model_routing_is_account_owned_and_preview_has_no_task_effects(env_with_main_agent):
    client, server, auth, agent = env_with_main_agent
    repos = server.services.repos
    owner = repos.agent_repo.get(agent).user_id
    repos.provider_repo.create(
        user_id=owner,
        name="Routing",
        kind="openai",
        base_url="https://example.invalid/v1",
        api_key="fake",
        models_json=json.dumps(
            [{"id": "plain", "input": ["text"]}, {"id": "coder", "input": ["text"]}]
        ),
    )
    path = "/api/settings/model-routing"
    assert (await client.get(path)).status_code == 401
    saved = await client.put(
        path, headers=auth, json={"enabled": True, "tasks": {"coding": "Routing/coder"}}
    )
    assert saved.status_code == 200
    assert saved.json()["tasks"]["coding"] == "Routing/coder"
    assert "fake" not in saved.text
    with repos.db.connect() as conn:
        before = tuple(
            conn.execute(
                "SELECT (SELECT COUNT(*) FROM usage_log), (SELECT COUNT(*) FROM threads), (SELECT COUNT(*) FROM work_items)"
            ).fetchone()
        )
    preview = await client.post(path + "/preview", headers=auth, json={"text": "修复 Python 报错"})
    assert preview.status_code == 200
    assert preview.json() == {
        "task": "coding",
        "model": "Routing/coder",
        "source": "task",
        "reason": "task_model",
        "available": True,
    }
    with repos.db.connect() as conn:
        after = tuple(
            conn.execute(
                "SELECT (SELECT COUNT(*) FROM usage_log), (SELECT COUNT(*) FROM threads), (SELECT COUNT(*) FROM work_items)"
            ).fetchone()
        )
    assert before == after
    other = await create_user(client, auth, username="routing-other")
    view = (await client.get(path, headers=other)).json()
    assert not view["enabled"] and not view["tasks"]
    assert all(model["provider_name"] != "Routing" for model in view["models"])
    rejected = await client.put(
        path, headers=other, json={"enabled": True, "tasks": {"coding": "Routing/coder"}}
    )
    assert rejected.status_code == 400
    assert "MODEL_ROUTING_INVALID_MODEL" in rejected.text
    assert (
        await client.post(path + "/preview", headers=auth, json={"text": "test", "user_id": owner})
    ).status_code == 422
    assert (
        await client.post(path + "/preview", headers=auth, json={"text": "x" * 20001})
    ).status_code == 422


@pytest.mark.asyncio
async def test_machine_credentials_cannot_read_or_change_model_routes(env_with_main_agent):
    client, server, auth, agent = env_with_main_agent
    minted = await client.post(
        "/api/auth/agent-access-keys",
        headers=auth,
        json={
            "name": "routing-boundary",
            "days": 1,
            "expert_ids": [agent],
            "scopes": ["tasks.read"],
        },
    )
    assert minted.status_code == 201
    machine = {"Authorization": "Bearer " + minted.json()["secret"]}
    path = "/api/settings/model-routing"
    assert (await client.get(path, headers=machine)).status_code == 403
    assert (await client.put(path, headers=machine, json={"enabled": True})).status_code == 403
    assert (
        await client.post(path + "/preview", headers=machine, json={"text": "test"})
    ).status_code == 403
