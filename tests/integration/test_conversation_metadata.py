"""0035 HTTP authorization, corrections, idempotency and generated API contracts."""

from __future__ import annotations

import pytest

from tests.support.auth import create_user


@pytest.mark.asyncio
async def test_metadata_routes_enforce_owner_cas_and_job_idempotency(env_with_main_agent):
    client, server, auth, agent = env_with_main_agent
    repos = server.services.repos
    owner = repos.agent_repo.get(agent).user_id
    repos.thread_repo.insert(
        thread_id="metadata-http",
        agent_id=agent,
        user_id=owner,
        channel_type="dashboard",
        session_key="metadata-http",
    )
    scope = f"/api/agents/{agent}/threads/metadata-http"
    settings = (await client.get("/api/settings/conversation-metadata", headers=auth)).json()
    assert settings["title_enabled"]
    body = {
        k: settings[k]
        for k in ("revision", "title_enabled", "brief_enabled", "title_model", "brief_model")
    }
    body["title_enabled"] = False
    assert (
        await client.put("/api/settings/conversation-metadata", headers=auth, json=body)
    ).status_code == 200
    assert (
        await client.put("/api/settings/conversation-metadata", headers=auth, json=body)
    ).status_code == 409
    before = await client.get(scope + "/brief", headers=auth)
    assert before.status_code == 200
    correction = {
        "expected_revision": before.json()["revision"],
        "objective": "人工目标",
        "note": "不会被后台覆盖",
    }
    after = await client.patch(scope + "/brief", headers=auth, json=correction)
    assert after.status_code == 200
    assert after.json()["overview"]["objective"] == "人工目标"
    assert (await client.patch(scope + "/brief", headers=auth, json=correction)).status_code == 409
    request = {"kind": "title", "command_id": "same-command"}
    job = await client.post(scope + "/metadata-jobs", headers=auth, json=request)
    duplicate = await client.post(scope + "/metadata-jobs", headers=auth, json=request)
    assert job.status_code == duplicate.status_code == 202
    assert job.json()["job_id"] == duplicate.json()["job_id"]
    other = await create_user(client, auth, username="other-metadata")
    for suffix in (
        "/brief",
        "/events",
        "/metadata-source?kind=event&id=missing",
        "/metadata-jobs/" + job.json()["job_id"],
    ):
        assert (await client.get(scope + suffix, headers=other)).status_code == 403
    assert (
        await client.post(scope + "/digests", headers=other, json={"window": "today"})
    ).status_code == 403
    assert (
        await client.get(scope + "/events", headers=auth, params={"cursor": "bad"})
    ).status_code == 400
    schema = client._octop_app.openapi()
    for suffix in ("/brief", "/metadata-jobs", "/digests", "/events"):
        path = f"/api/agents/{{agent_id}}/threads/{{thread_id}}{suffix}"
        assert path in schema["paths"]
        assert all(operation.get("summary") for operation in schema["paths"][path].values())
