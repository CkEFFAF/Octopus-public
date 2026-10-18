"""Actual AgentManager assembly and full app routes use the same share authority."""

import json
from dataclasses import replace

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.config import var_child_runnable_config

from octop.infra.history.projection import message_inputs


async def test_assembled_native_sharing_full_app_http_and_mode_policy(env_with_agent):
    client, server, auth, aid = env_with_agent
    registry = server.app_runtime.agent_registry
    uid = registry.get_row(aid).user_id
    shared = registry._native_management_context["sharing"]
    shared.config = replace(shared.config, public_origin="https://share.example.com")
    server.services = replace(server.services, config=shared.config)
    tid = (await client.post(f"/api/agents/{aid}/threads", headers=auth)).json()["thread_id"]
    server.services.thread_message_repo.replace_all(
        tid,
        message_inputs(
            [
                HumanMessage(content="Synthetic sharing question"),
                AIMessage(
                    content="Synthetic answer",
                    additional_kwargs={"reasoning_content": "PRIVATE_REASONING"},
                ),
            ]
        ),
    )
    assembled = registry._harness_manager.get_agent(aid).config
    tools = {tool.name: tool for tool in assembled.tools}
    expected = {
        "octop_thread_share_" + suffix for suffix in ("preview", "create", "list", "revoke")
    }
    assert expected <= tools.keys()
    runtime = {"configurable": {"user": uid, "thread_id": tid, "conversation_mode": "craft"}}
    marker = var_child_runnable_config.set(runtime)
    try:

        async def call(suffix, **args):
            return json.loads(await tools["octop_thread_share_" + suffix].ainvoke(args))

        preview = await call("preview")
        assert "preview_digest" in preview, preview
        created = await call(
            "create", preview_digest=preview["preview_digest"], expires_in_seconds=86400
        )
        assert created["public_url"].startswith("https://share.example.com/share/"), created
        public = "/api/public/thread-shares/" + created["public_path"].rsplit("/", 1)[1]
        response = await client.get(public)
        assert response.status_code == 200 and "PRIVATE_REASONING" not in response.text
        listed = (await client.get("/api/thread-shares", headers=auth)).json()
        assert listed["shares"][0]["share_id"] == created["share_id"]
        assert listed["shares"][0]["public_url"] == created["public_url"]
        readonly = var_child_runnable_config.set(
            {"configurable": {**runtime["configurable"], "conversation_mode": "ask"}}
        )
        try:
            assert (await call("revoke", share_id=created["share_id"]))["error"][
                "code"
            ] == "FORBIDDEN"
            assert (await call("list"))["shares"]
        finally:
            var_child_runnable_config.reset(readonly)
        assert (await call("revoke", share_id=created["share_id"]))["status"] == "revoked"
        assert (await client.get(public)).status_code == 404
    finally:
        var_child_runnable_config.reset(marker)
