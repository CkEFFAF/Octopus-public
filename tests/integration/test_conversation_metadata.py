"""0035 HTTP authorization, corrections, idempotency and generated API contracts."""

from __future__ import annotations

import pytest

from tests.support.auth import create_user


@pytest.mark.asyncio
async def test_account_history_batch_http_restores_progress_and_isolates_users(
    env_with_main_agent, monkeypatch
):
    client, server, auth, agent = env_with_main_agent
    repos = server.services.repos
    owner = repos.agent_repo.get(agent).user_id
    # No external model calls: exercise the real router, authentication and database queue.
    monkeypatch.setattr(
        "octop.infra.conversations.service.ConversationService.resolve_model",
        lambda *args: "test/model",
    )
    for i in range(61):
        repos.thread_repo.insert(
            thread_id=f"batch-http-{i}",
            agent_id=agent,
            user_id=owner,
            channel_type="dashboard",
            session_key=f"batch-http-{i}",
        )
    url = "/api/settings/conversation-metadata/batch"
    assert (await client.get(url)).status_code == 401
    started = await client.post(url, headers=auth, json={"command_id": "all-http"})
    assert started.status_code == 202
    assert started.json()["total"] >= 61
    restored = (await client.get(url, headers=auth)).json()
    assert restored["batch_id"] == "all-http" and restored["total"] == started.json()["total"]
    duplicate = await client.post(url, headers=auth, json={"command_id": "double-click"})
    assert duplicate.json()["batch_id"] == "all-http"
    other = await create_user(client, auth, username="batch-other")
    assert (await client.get(url, headers=other)).json() is None
    invalid = await client.post(
        url,
        headers=other,
        json={"command_id": "foreign-http", "agent_id": agent, "thread_ids": ["batch-http-0"]},
    )
    assert invalid.status_code == 403
    assert "HistoryBatchRequest" in client._octop_app.openapi()["components"]["schemas"]
    history_url = "/api/settings/conversation-metadata/conversations"
    with repos.db.transaction() as conn:
        conn.execute(
            "UPDATE thread_metadata_jobs SET status='failed',error_code='METADATA_INVALID_OUTPUT' WHERE thread_id='batch-http-0'"
        )
    params = {"batch_id": "all-http", "status_filter": "failed"}
    assert (await client.get(history_url, params=params)).status_code == 401
    page = (await client.get(history_url, headers=auth, params=params)).json()
    assert page["total"] == 1 and page["items"][0]["thread_id"] == "batch-http-0"
    assert (await client.get(history_url, headers=other, params=params)).json()["total"] == 0


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
