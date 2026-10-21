"""Authenticated input controls through the running app and its database."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from tests.support.app import octop_client, write_octop_config
from tests.support.auth import (
    auth_header,
    bootstrap_admin,
    create_agent,
    ensure_users,
    seed_openai_provider,
)


@pytest.mark.asyncio
async def test_durable_inputs_auth_retry_withdraw_and_schema(tmp_octop_home):
    write_octop_config(tmp_octop_home, enable_api_docs=True)
    async with octop_client(tmp_octop_home) as (client, server):
        await bootstrap_admin(client, tmp_octop_home)
        admin = await auth_header(client)
        users = await ensure_users(client, admin, "alice", "bob")
        await seed_openai_provider(client, users["alice"])
        agent = await create_agent(client, users["alice"])
        response = await client.post(f"/api/agents/{agent}/threads", headers=users["alice"])
        thread = response.json()["thread_id"]
        base = f"/api/agents/{agent}/threads/{thread}/inputs"
        # Keep admission pending so refresh and withdrawal exercise durable state.
        await server.app_runtime.gateway.inputs.close()
        body = {
            "command_id": "queue-one",
            "snapshot": {"text": "hello", "createdAt": 1},
            "turn": {"type": "user_turn", "thread_id": thread, "text": "hello"},
        }
        denied = await client.get(base, headers=users["bob"])
        assert denied.status_code == 403
        queued = await client.post(base, headers=users["alice"], json=body)
        assert queued.status_code == 200, queued.text
        assert queued.json()["status"] == "queued"
        retry = await client.post(base, headers=users["alice"], json=body)
        assert retry.json()["event_id"] == queued.json()["event_id"]
        body["turn"]["text"] = "changed"
        assert (await client.post(base, headers=users["alice"], json=body)).status_code == 409
        promotion = await client.post(
            base + "/queue-one/steer",
            headers=users["alice"],
            json={"run_id": "stale"},
        )
        assert promotion.status_code == 409
        after_rejection = await client.get(base, headers=users["alice"])
        promoted_receipt = after_rejection.json()["inputs"][0]
        assert promoted_receipt["event_id"] == queued.json()["event_id"]
        assert promoted_receipt["kind"] == "chat_input"
        assert promoted_receipt["status"] == "queued"
        assert promoted_receipt["payload"]["snapshot"]["text"] == "hello"
        listed = await client.get(base, headers=users["alice"])
        assert len(listed.json()["inputs"]) == 1
        withdrawn = await client.delete(base + "/queue-one", headers=users["alice"])
        assert withdrawn.json()["status"] == "withdrawn"
        queued_now = await client.post(
            base,
            headers=users["alice"],
            json={
                "command_id": "queue-now",
                "snapshot": {"text": "handle now"},
                "turn": {"type": "user_turn", "thread_id": thread, "text": "handle now"},
            },
        )
        assert queued_now.status_code == 200
        now_path = base + "/queue-now/steer"
        invalid_mode = await client.post(
            now_path, headers=users["alice"], json={"run_id": "run", "cancel_tools": "true"}
        )
        assert invalid_mode.status_code == 422
        denied_now = await client.post(
            now_path, headers=users["bob"], json={"run_id": "run", "cancel_tools": True}
        )
        assert denied_now.status_code == 403
        with patch.object(
            server.app_runtime.gateway.inputs.agents,
            "steer_stream",
            Mock(return_value={"status": "accepted", "phase": "tool_running"}),
        ) as steer:
            immediate = await client.post(
                now_path, headers=users["alice"], json={"run_id": "run", "cancel_tools": True}
            )
            assert immediate.status_code == 200, immediate.text
            assert immediate.json()["payload"]["cancel_tools"] is True
            retry_now = await client.post(
                now_path, headers=users["alice"], json={"run_id": "run", "cancel_tools": True}
            )
            assert retry_now.json()["event_id"] == immediate.json()["event_id"]
            steer.assert_called_once_with(
                agent, thread, "queue-now", "handle now", run_id="run", cancel_tools=True
            )
        dismiss_path = base + "/queue-now/dismiss"
        assert (await client.post(dismiss_path, headers=users["alice"])).status_code == 409
        owner = int(immediate.json()["event_id"].split(":")[1])
        server.app_runtime.gateway.inputs.repos.chat_input_repo.transition(
            owner, "queue-now", "accepted", "unknown"
        )
        assert (await client.post(dismiss_path, headers=users["bob"])).status_code == 403
        dismissed = await client.post(dismiss_path, headers=users["alice"])
        assert dismissed.status_code == 200
        assert dismissed.json()["status"] == "dismissed"
        assert (await client.post(dismiss_path, headers=users["alice"])).json()[
            "status"
        ] == "dismissed"
        inserted = await client.post(
            base + "/steer",
            headers=users["alice"],
            json={
                "command_id": "insert-one",
                "thread_id": thread,
                "run_id": "stale",
                "text": "direction",
            },
        )
        assert inserted.status_code == 200, inserted.text
        assert inserted.json()["status"] == "inactive"
        invalid = await client.post(
            base + "/steer",
            headers=users["alice"],
            json={"command_id": "bad", "thread_id": thread, "run_id": "stale", "text": "  "},
        )
        assert invalid.status_code == 422
        docs = await client.get("/api/docs")
        assert docs.status_code == 200
        spec = (await client.get("/api/openapi.json")).json()
        for method in ("get", "post"):
            route = spec["paths"]["/api/agents/{agent_id}/threads/{thread_id}/inputs"][method]
            assert route["summary"]
            assert "$ref" in route["responses"]["200"]["content"]["application/json"]["schema"]
        promote_route = spec["paths"][
            "/api/agents/{agent_id}/threads/{thread_id}/inputs/{command_id}/steer"
        ]["post"]
        assert promote_route["summary"]


@pytest.mark.asyncio
async def test_queued_prepare_does_not_mutate_running_selection():
    from octop.api.routers.chat.models import ChatTurnBody
    from octop.api.routers.chat.turn import prepare_dashboard_turn

    selection = SimpleNamespace(update_composer=AsyncMock())
    executions = SimpleNamespace(
        selection=lambda *a: {"work_mode": "agentic"},
        save_selection=AsyncMock(),
        has_target=lambda value: False,
        default_target=lambda *a: {},
        resolve=lambda *a, **k: SimpleNamespace(
            public=lambda: {"target_kind": "local"}, device_id=None, grant_version=1
        ),
    )
    runtime = SimpleNamespace(agent_registry=SimpleNamespace(), thread_registry=None)
    runtime.gateway = SimpleNamespace(thread_registry=selection)
    server = SimpleNamespace(app_runtime=runtime)
    user = SimpleNamespace(id=1)
    row = SimpleNamespace(default_model=None, config_json="{}")
    turn = ChatTurnBody(
        thread_id="thread",
        text="hello",
        target_kind="local",
        work_mode="debug",
        reasoning_mode="enabled",
    )
    with (
        patch("octop.api.routers.chat.turn.require_agent_row", return_value=row),
        patch("octop.api.routers.chat.turn.validate_chat_mcp_servers", AsyncMock(return_value=[])),
        patch("octop.api.routers.chat.turn.validate_chat_skills", AsyncMock(return_value=[])),
        patch(
            "octop.api.routers.chat.turn.resolve_thread_id",
            AsyncMock(return_value=("thread", "session")),
        ),
        patch("octop.infra.execution.service.ExecutionService", return_value=executions),
    ):
        runtime.devices = SimpleNamespace()
        await prepare_dashboard_turn(
            server, agent_id="agent", user=user, turn=turn, persist_selection=False
        )
    selection.update_composer.assert_not_called()
    executions.save_selection.assert_not_called()
