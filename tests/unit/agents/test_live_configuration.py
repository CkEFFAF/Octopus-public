from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.skills import SkillsMiddleware
from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.config import var_child_runnable_config
from langgraph.prebuilt.tool_node import ToolCallRequest
from pydantic import Field

from octop.infra.agents.middleware.live_configuration import (
    LiveConfigurationMiddleware,
    remember_self_update,
)
from octop.infra.connectors.catalog import get_catalog_entry
from octop.infra.connectors.gateway.langchain import build_gateway_langchain_tools


class RecordingModel(FakeMessagesListChatModel):
    seen: list[list[str]] = Field(default_factory=list)
    prompts: list[str] = Field(default_factory=list)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.prompts.append(str(messages[0].content))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def bind_tools(self, tools: list, **kwargs: object) -> RecordingModel:
        self.seen.append([item.name for item in tools])
        return self


@pytest.fixture
def live() -> SimpleNamespace:
    instance = SimpleNamespace(
        kind="qq-mail",
        instance_id="mail",
        mcp_server_name="qq-mail__mail",
        status="active",
        has_credentials=True,
    )
    workspace = SimpleNamespace(skill_catalog_roots=lambda **kwargs: [])
    agent = SimpleNamespace(
        _mcp_tool_name_set=frozenset(),
        workspace=workspace,
        config=SimpleNamespace(skills_dir=None),
    )
    row = SimpleNamespace(agent_id="expert", user_id=1, config_json="{}", mcp_servers="[]")
    service = SimpleNamespace(
        custom_harness_configs=lambda owner: {},
        ensure_fresh_credentials=AsyncMock(
            return_value={"email": "fake", "password": "version-one"}
        ),
    )
    manager = SimpleNamespace(
        get_row=lambda identity: row,
        get_agent=lambda identity: agent,
        get_config=lambda identity: {},
        sync_skill_package_dirs=lambda *args, **kwargs: None,
        default_mcp_servers=lambda identity: json.loads(row.mcp_servers),
        device_mcp_pack_for_turn=lambda *args, **kwargs: ([], [], None),
        merge_turn_mcp_servers=lambda owner, explicit, **kwargs: (
            explicit if explicit is not None else kwargs["extra_defaults"]
        ),
        _connector_svc=service,
        _repos=SimpleNamespace(
            connector_repo=SimpleNamespace(
                list_visible=lambda owner: [instance] if owner == 1 else []
            ),
            user_repo=SimpleNamespace(get=lambda owner: SimpleNamespace(disabled=False)),
        ),
    )
    cfg = {
        "user": 1,
        "agent_id": "expert",
        "thread_id": "thread",
        "octop_task_run_id": "run",
        "mcp_servers": [],
    }
    middleware = LiveConfigurationMiddleware(manager, "expert")
    return SimpleNamespace(
        manager=manager, instance=instance, agent=agent, row=row, cfg=cfg, middleware=middleware
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "installed_harness, tool_search", [(False, False), (True, False), (True, True)]
)
async def test_same_graph_uses_new_connector_after_self_update(
    live: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    installed_harness: bool,
    tool_search: bool,
) -> None:
    calls = []

    def gateway(**kwargs: object) -> dict:
        calls.append(kwargs)
        return {"result": {"content": [{"type": "text", "text": "synthetic inbox"}]}}

    monkeypatch.setattr("octop.infra.connectors.gateway.langchain.handle_mcp_request", gateway)
    mail_tools = build_gateway_langchain_tools(
        entry=get_catalog_entry("qq-mail"),
        instance_id="mail",
        mcp_server_name=live.instance.mcp_server_name,
        creds={},
    )
    search_name = next(item.name for item in mail_tools if item.name.endswith("search_emails"))

    @tool
    def configure_mailbox() -> str:
        """Save the current expert's mailbox connector selection."""
        live.row.mcp_servers = json.dumps([live.instance.mcp_server_name])
        assert remember_self_update(live.manager, "expert", [live.instance.mcp_server_name])
        return "saved"

    model = RecordingModel(
        responses=[
            AIMessage(
                content="", tool_calls=[{"name": "configure_mailbox", "args": {}, "id": "save"}]
            ),
            AIMessage(
                content="", tool_calls=[{"name": search_name, "args": {"limit": 1}, "id": "read"}]
            ),
            AIMessage(content="done"),
        ]
    )
    if tool_search:
        model.responses.insert(
            1,
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "tool_search",
                        "args": {"query": "search_emails", "max_results": 5},
                        "id": "search",
                    }
                ],
            ),
        )
    if installed_harness:
        from pathlib import Path

        from octop_harness.agent import HarnessAgent
        from octop_harness.config import HarnessAgentConfig
        from octop_harness.middleware.conversation_mode import ConversationModeMiddleware
        from octop_harness.middleware.mcp_tools import MCPToolMiddleware
        from octop_harness.middleware.tool_search import ToolSearchMiddleware
        from octop_harness.middleware.tools_filter import ToolsFilterMiddleware

        config = HarnessAgentConfig(providers=[], subagents_auto_load=False)
        harness = HarnessAgent.__new__(HarnessAgent)
        harness._config = config
        harness._backend = None
        monkeypatch.setattr(harness, "_resolve_checkpointer", lambda: None)
        monkeypatch.setattr(harness, "_build_seed_model", lambda: model)
        monkeypatch.setattr(harness, "_agent_visible_workspace_dir", Path.cwd)
        monkeypatch.setattr(harness, "_resolve_interrupt_on", lambda: None)
        graph = harness._build_graph(
            tools=[configure_mailbox],
            middleware=[
                MCPToolMiddleware(
                    server_names=frozenset(), mcp_tool_names=frozenset(), default_servers=None
                ),
                live.middleware,
                ConversationModeMiddleware(),
                ToolsFilterMiddleware(config=config),
                *(
                    [ToolSearchMiddleware(deferred_tools=frozenset(), defer_mcp_tools=True)]
                    if tool_search
                    else []
                ),
            ],
            skills=[],
            memory=[],
        )
    else:
        graph = create_agent(model, tools=[configure_mailbox], middleware=[live.middleware])
    result = await graph.ainvoke(
        {"messages": [("user", "configure and read")]}, {"configurable": live.cfg}
    )
    assert search_name not in model.seen[0]
    assert search_name in model.seen[1]
    assert any(
        isinstance(message, ToolMessage) and "synthetic inbox" in message.content
        for message in result["messages"]
    )
    assert calls[0]["creds"]["password"] == "version-one"


@pytest.mark.asyncio
async def test_updates_are_run_scoped_and_revocation_blocks_old_tools(
    live: SimpleNamespace,
) -> None:
    token = var_child_runnable_config.set({"configurable": live.cfg})
    try:
        assert remember_self_update(live.manager, "expert", [live.instance.mcp_server_name])
        tools = await live.middleware._tools(live.cfg)
        assert tools
        assert not await live.middleware._tools({**live.cfg, "thread_id": "another"})
        live.instance.status = "disabled"
        request = ToolCallRequest(
            tool_call={"name": tools[0].name, "args": {}, "id": "old"},
            tool=tools[0],
            state={},
            runtime=None,
        )
        handler = AsyncMock()
        result = await live.middleware.awrap_tool_call(request, handler)
        assert result.status == "error"
        handler.assert_not_called()
    finally:
        var_child_runnable_config.reset(token)


@pytest.mark.asyncio
async def test_execution_resolves_rotated_credentials(
    live: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = {**live.cfg, "mcp_servers": [live.instance.mcp_server_name]}
    tools = await live.middleware._tools(cfg)
    live.manager._connector_svc.ensure_fresh_credentials.return_value = {"password": "version-two"}
    captured = []
    monkeypatch.setattr(
        "octop.infra.connectors.gateway.langchain.handle_mcp_request",
        lambda **kwargs: captured.append(kwargs) or {"result": {"content": []}},
    )
    request = ToolCallRequest(
        tool_call={"name": tools[0].name, "args": {}, "id": "rotated"},
        tool=tools[0],
        state={},
        runtime=None,
    )
    token = var_child_runnable_config.set({"configurable": cfg})
    try:

        async def execute(prepared: ToolCallRequest) -> str:
            return await prepared.tool.ainvoke({})

        await live.middleware.awrap_tool_call(request, execute)
    finally:
        var_child_runnable_config.reset(token)
    assert captured[0]["creds"] == {"password": "version-two"}


@pytest.mark.asyncio
async def test_skills_refresh_stale_checkpoint_metadata(live: SimpleNamespace) -> None:
    workspace = live.agent.workspace
    workspace.skill_catalog_roots = lambda **kwargs: [("skills", "workspace")]
    workspace.als = AsyncMock(
        return_value=SimpleNamespace(entries=[{"path": "skills/new-skill", "is_dir": True}])
    )
    workspace.aread_text = AsyncMock(
        return_value="---\nname: new-skill\ndescription: newly installed\n---\nbody"
    )
    request = ModelRequest(
        model=RecordingModel(responses=[AIMessage(content="unused")]),
        messages=[],
        tools=[],
        state={"messages": [], "skills_metadata": []},
    )
    prepared = await live.middleware._prepare(request, live.cfg)
    assert [item["name"] for item in prepared.state["skills_metadata"]] == ["new-skill"]
    assert request.state["skills_metadata"] == []
    live.manager.get_config = lambda identity: {"skills_disabled": ["new-skill"]}
    assert not (await live.middleware._prepare(request, live.cfg)).state["skills_metadata"]


@pytest.mark.asyncio
async def test_new_skill_reaches_the_running_graph_system_prompt(
    live: SimpleNamespace, tmp_path
) -> None:
    installed = False
    workspace = live.agent.workspace
    workspace.skill_catalog_roots = lambda **kwargs: [("skills", "workspace")]

    async def listing(root):
        return SimpleNamespace(
            entries=[{"path": "skills/new-skill", "is_dir": True}] if installed else []
        )

    workspace.als = listing
    workspace.aread_text = AsyncMock(
        return_value="---\nname: new-skill\ndescription: newly installed\n---\nbody"
    )

    @tool
    def install_skill() -> str:
        """Install a synthetic skill without executing downloaded code."""
        nonlocal installed
        installed = True
        return "installed"

    model = RecordingModel(
        responses=[
            AIMessage(
                content="", tool_calls=[{"name": "install_skill", "args": {}, "id": "install"}]
            ),
            AIMessage(content="done"),
        ]
    )
    skills = SkillsMiddleware(backend=FilesystemBackend(root_dir=str(tmp_path)), sources=[])
    graph = create_agent(model, tools=[install_skill], middleware=[live.middleware, skills])
    await graph.ainvoke(
        {"messages": [("user", "install")], "skills_metadata": []},
        {"configurable": live.cfg},
    )
    assert "newly installed" not in model.prompts[0]
    assert "newly installed" in model.prompts[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["ask", "plan"])
async def test_mode_and_owner_boundaries(live: SimpleNamespace, mode: str) -> None:
    assert not await live.middleware._tools(
        {**live.cfg, "mcp_servers": [live.instance.mcp_server_name], "conversation_mode": mode}
    )
    assert not await live.middleware._tools(
        {**live.cfg, "user": 2, "mcp_servers": [live.instance.mcp_server_name]}
    )


def test_explicit_local_execution_does_not_follow_a_new_device_binding(
    live: SimpleNamespace,
) -> None:
    def unexpected(*args, **kwargs):
        pytest.fail("A frozen local run must not resolve a newly configured device")

    live.manager.device_mcp_pack_for_turn = unexpected
    assert (
        live.middleware._selection({**live.cfg, "octop_execution_context": {"device_id": None}})
        == []
    )
