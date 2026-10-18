"""Native product operations persist resources visible through the existing HTTP API."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langgraph.config import var_child_runnable_config
from pydantic import ValidationError

from octop.infra.agents.native_management_tools import build_native_management_tools
from octop.infra.agents.settings.tool_catalog import NATIVE_TOOL_NAMES
from octop.infra.agents.subagents import service as subagent_service
from octop.infra.agents.teams.service import HOST_TOOLS_ALLOWED, HOST_TOOLS_DISABLED
from octop.infra.db.repos.thread_messages import ThreadMessageInput


@pytest.fixture
def native(env_with_agent: Any) -> Any:
    client, server, auth, aid = env_with_agent
    registry = server.app_runtime.agent_registry
    uid = registry.get_row(aid).user_id
    tools = {
        tool.name: tool
        for tool in build_native_management_tools(
            registry,
            server.services.repos,
            aid,
            catalog=server.subagent_catalog,
            execution=server.app_runtime.execution,
            turn_active=server.app_runtime.gateway.ws_hub.is_turn_active,
        )
    }
    token = var_child_runnable_config.set({"configurable": {"user": uid, "work_mode": "agentic"}})
    yield client, server, auth, aid, uid, tools
    var_child_runnable_config.reset(token)


async def call(tools: Any, tool_name: str, **args: Any) -> dict[str, Any]:
    return json.loads(await tools[tool_name].ainvoke(args))


async def test_owned_expert_device_defaults_create_update_clear_and_reject(native, tmp_path):
    _c, srv, _auth, _aid, uid, tools = native
    devices = srv.app_runtime.devices
    enrolled = devices.enroll(
        owner_user_id=uid,
        name="Cloud",
        platform="linux",
        capabilities=["files_read"],
        permissions=["files_read"],
        roots=[],
        trust_mode="owner",
    )
    did = enrolled["device"]["device_id"]
    created = await call(
        tools,
        "octop_expert_create",
        name="Bound expert",
        device_binding={"device_id": did, "working_dir": str(tmp_path)},
    )
    assert created["saved"] and created["default_target"]["device_id"] == did
    aid = created["agent_id"]
    updated = await call(
        tools, "octop_expert_update", target_agent_id=aid, description="Still bound"
    )
    assert updated["default_target"]["device_id"] == did
    for binding in (
        {"device_id": "foreign"},
        {"target_kind": "local", "device_id": did},
        {"device_id": did, "working_dir": "bad\x00dir"},
        {"device_id": did, "grant_version": 999},
    ):
        rejected = await call(
            tools,
            "octop_expert_update",
            target_agent_id=aid,
            name="Must not persist",
            device_binding=binding,
        )
        assert "error" in rejected
        assert srv.app_runtime.agent_registry.get_row(aid).name == "Bound expert"
    cleared = await call(tools, "octop_expert_update", target_agent_id=aid, device_binding={})
    assert cleared["default_target"] is None
    local = await call(
        tools,
        "octop_expert_update",
        target_agent_id=aid,
        device_binding={"target_kind": "local", "working_dir": str(tmp_path)},
    )
    assert local["default_target"]["target_kind"] == "local"


async def test_expert_configuration_subagent_and_group_are_real(native: Any) -> None:
    c, srv, auth, aid, uid, tools = native
    registry = srv.app_runtime.agent_registry
    created = await call(
        tools,
        "octop_expert_create",
        name="Review expert",
        system_prompt="Review evidence.",
        welcome_message="Send a draft.",
    )
    assert created["saved"] is True, created
    new_id = created["agent_id"]
    response = await c.get(f"/api/agents/{new_id}", headers=auth)
    assert response.status_code == 200
    assert response.json()["system_prompt"] == "Review evidence."
    assert response.json()["welcome_message"] == "Send a draft."
    before = registry.get_row(new_id)
    rejected = await call(
        tools,
        "octop_expert_update",
        target_agent_id=new_id,
        name="Must not change",
        knowledge_base_ids=["missing"],
    )
    assert "error" in rejected
    assert registry.get_row(new_id).name == before.name
    bad_model = await call(
        tools,
        "octop_expert_update",
        target_agent_id=new_id,
        default_model="secret-provider/invalid",
        description="No write",
    )
    assert "error" in bad_model
    assert registry.get_row(new_id).description == before.description
    updated = await call(
        tools,
        "octop_expert_update",
        target_agent_id=new_id,
        description="Reviewer",
        default_model="auto",
        welcome_message="",
    )
    assert updated["description"] == "Reviewer"
    assert updated["welcome_message"] is None

    saved = await call(
        tools,
        "octop_subagent_save",
        target_agent_id=new_id,
        slug="evidence-checker",
        name="Evidence: checker",
        description="Check sources",
        instructions="Inspect evidence and report gaps.",
    )
    assert saved["saved"] is True, saved
    # Definition is persisted before the deferred graph refresh.
    content = await registry.workspace_for_agent(new_id).aread_text("agents/evidence-checker.md")
    assert "Evidence: checker" in content
    await registry.reload(new_id)
    rows = (await c.get(f"/api/agents/{new_id}/subagents", headers=auth)).json()
    assert "evidence-checker" in {row["slug"] for row in rows}
    duplicate = await call(
        tools,
        "octop_subagent_save",
        target_agent_id=new_id,
        slug="evidence-checker",
        name="Changed",
        description="x",
        instructions="x",
    )
    assert "error" in duplicate
    assert (
        await registry.workspace_for_agent(new_id).aread_text("agents/evidence-checker.md")
        == content
    )
    replaced = await call(
        tools,
        "octop_subagent_save",
        target_agent_id=new_id,
        slug="evidence-checker",
        name="Changed",
        description="x",
        instructions="Updated instruction",
        replace=True,
    )
    assert replaced["saved"]
    invalid = await call(
        tools, "octop_subagent_save", slug="../escape", name="x", description="", instructions="x"
    )
    assert "error" in invalid
    empty = await call(
        tools, "octop_subagent_save", slug="empty", name="Empty", description="", instructions=""
    )
    assert "error" in empty
    assert await registry.workspace_for_agent(aid).aread_text("agents/empty.md") is None
    installed = await call(
        tools,
        "octop_subagent_install",
        target_agent_id=new_id,
        slug="engineering-software-architect",
        locale="en",
    )
    assert installed["saved"] and installed["locale"] == "en"

    project = await call(
        tools, "octop_project_create", name="Review group", member_ids=[aid, new_id]
    )
    assert project["saved"] is True, project
    assert project["thread_id"]
    group_id = project["agent_id"]
    group = (await c.get(f"/api/teams/{group_id}", headers=auth)).json()
    assert set(group["member_ids"]) == {aid, new_id}
    configured = await call(
        tools,
        "octop_project_update",
        project_id=group_id,
        name="Edited review group",
        description="Budget review",
        welcome_message="Compare evidence",
        default_model="auto",
    )
    assert configured["name"] == "Edited review group"
    assert (await c.get(f"/api/teams/{group_id}", headers=auth)).json()[
        "description"
    ] == "Budget review"
    rejected_group = await call(
        tools,
        "octop_project_update",
        project_id=group_id,
        name="No mutation",
        default_model="missing/model",
    )
    assert "error" in rejected_group
    assert registry.get_row(group_id).name == "Edited review group"
    assert srv.services.thread_repo.get(project["thread_id"]).agent_id == group_id
    registry.teams.jobs.begin(group_id, new_id)
    third = await call(tools, "octop_expert_create", name="Third expert")
    busy = await call(
        tools,
        "octop_project_update_members",
        project_id=group_id,
        add_member_ids=[third["agent_id"]],
        remove_member_ids=[new_id],
    )
    assert "error" in busy
    assert set(registry.teams.member_ids(group_id)) == {aid, new_id}
    registry.teams.jobs.end(group_id, new_id)
    changed = await call(
        tools,
        "octop_project_update_members",
        project_id=group_id,
        add_member_ids=[f" {third['agent_id']} "],
        remove_member_ids=[f" {new_id} "],
    )
    assert set(changed["member_ids"]) == {aid, third["agent_id"]}
    cfg = registry._build_harness_config(registry.get_row(group_id))
    assert {tool.name for tool in cfg.tools} >= {
        "octop_project_update_members",
        "octop_thread_search",
    }
    assert "execute" in cfg.tools_disabled
    assert "octop_project_update_members" not in cfg.tools_disabled


async def test_security_shared_discovery_and_mode_guard(native: Any) -> None:
    _c, srv, _auth, aid, uid, tools = native
    repos = srv.services.repos
    other = repos.user_repo.create(username="foreign", password_hash="unused", role="user")
    repos.agent_repo.create(agent_id="foreign-private", user_id=other, name="Foreign")
    repos.agent_repo.create(
        agent_id="foreign-shared",
        user_id=other,
        name="Shared",
        system_prompt="private-system",
        config_json='{"api_key":"NEVER_EXPOSE"}',
    )
    repos.agent_repo.set_shared("foreign-shared", True)
    listed = await call(tools, "octop_expert_list")
    assert "foreign-shared" in {row["agent_id"] for row in listed["experts"]}
    assert "foreign-private" not in {row["agent_id"] for row in listed["experts"]}
    shared = await call(tools, "octop_expert_get", target_agent_id="foreign-shared")
    assert shared["writable"] is False
    assert "private-system" not in json.dumps(shared)
    assert "NEVER_EXPOSE" not in json.dumps(shared)
    assert "error" in await call(
        tools, "octop_expert_update", target_agent_id="foreign-shared", name="denied"
    )
    for mode_key in ("conversation_mode", "work_mode"):
        for mode in ("ask", "plan"):
            token = var_child_runnable_config.set({"configurable": {"user": uid, mode_key: mode}})
            try:
                assert "experts" in await call(tools, "octop_expert_list")
                assert "error" in await call(tools, "octop_expert_create", name="Forbidden")
                assert "error" in await call(
                    tools,
                    "octop_subagent_save",
                    name="x",
                    slug="x",
                    description="",
                    instructions="x",
                )
            finally:
                var_child_runnable_config.reset(token)
    repos.user_repo.set_disabled(uid, True)
    assert "error" in await call(tools, "octop_expert_list")
    repos.user_repo.set_disabled(uid, False)
    assert any(
        json.loads(row.payload)["status"] == "denied_or_failed"
        for row in repos.audit_repo.query(action="octop_expert_create")
    )
    with pytest.raises(ValidationError):
        await tools["octop_expert_update"].ainvoke({"target_agent_id": aid, "config_json": "{}"})


async def test_owned_history_search_is_literal_bounded_and_text_only(native: Any) -> None:
    _c, srv, _auth, aid, uid, tools = native
    repos = srv.services.repos
    other = repos.user_repo.create(username="reader-other", password_hash="h", role="user")
    repos.agent_repo.create(agent_id="shared-reader", user_id=other, name="Shared reader")
    repos.agent_repo.set_shared("shared-reader", True)
    own = await call(tools, "octop_thread_create", title="Budget 100%_literal")
    shared = await call(
        tools, "octop_thread_create", target_agent_id="shared-reader", title="Shared discussion"
    )
    foreign_tid = "foreign-thread"
    repos.thread_repo.insert(
        thread_id=foreign_tid,
        agent_id=aid,
        user_id=other,
        channel_type="dashboard",
        session_key="foreign",
        title="Budget 100%_literal",
        last_active=0,
    )
    for tid in (own["thread_id"], shared["thread_id"]):
        repos.thread_message_repo.replace_all(
            tid,
            [
                ThreadMessageInput(
                    "u",
                    "human",
                    json.dumps(
                        {
                            "type": "human",
                            "data": {
                                "content": [
                                    "ignore scalar",
                                    {"type": "text", "text": "budget-token"},
                                    {"type": "image_url", "image_url": "SECRET_ATTACHMENT"},
                                ]
                            },
                        }
                    ),
                    1,
                ),
                ThreadMessageInput(
                    "a",
                    "ai",
                    json.dumps(
                        {
                            "type": "ai",
                            "data": {
                                "content": "Answer",
                                "tool_calls": [{"args": "SECRET_TOOL"}],
                                "additional_kwargs": {"reasoning_content": "SECRET_REASONING"},
                            },
                        }
                    ),
                    2,
                ),
                ThreadMessageInput(
                    "t", "tool", json.dumps({"type": "tool", "data": {"content": "SECRET_TOOL"}}), 3
                ),
            ],
        )
    literal = await call(tools, "octop_thread_search", query="%_")
    assert [row["thread_id"] for row in literal["threads"]] == [own["thread_id"]]
    found = await call(tools, "octop_thread_search", query="budget-token", limit=1)
    assert len(found["threads"]) == 1 and found["has_more"]
    next_page = await call(
        tools, "octop_thread_search", query="budget-token", limit=1, offset=found["next_offset"]
    )
    assert next_page["threads"][0]["thread_id"] != found["threads"][0]["thread_id"]
    assert all(
        row["thread_id"] != foreign_tid for row in [*found["threads"], *next_page["threads"]]
    )
    assert not (await call(tools, "octop_thread_search", query="SECRET_TOOL"))["threads"]
    history = await call(tools, "octop_thread_read", thread_id=shared["thread_id"])
    assert history["history_status"] == "ready"
    assert "budget-token" in json.dumps(history)
    for secret in ("SECRET_TOOL", "SECRET_REASONING", "SECRET_ATTACHMENT"):
        assert secret not in json.dumps(history)
    assert "error" in await call(tools, "octop_thread_read", thread_id=foreign_tid)
    repos.agent_repo.set_enabled("shared-reader", False)
    assert "error" in await call(tools, "octop_thread_read", thread_id=shared["thread_id"])
    assert "error" in await call(tools, "octop_thread_list", target_agent_id="shared-reader")
    assert shared["thread_id"] not in {
        row["thread_id"]
        for row in (await call(tools, "octop_thread_search", query="budget-token"))["threads"]
    }
    repos.agent_repo.set_enabled(aid, False)
    assert (await call(tools, "octop_thread_read", thread_id=own["thread_id"]))[
        "history_status"
    ] == "ready"
    assert own["thread_id"] in {
        row["thread_id"]
        for row in (await call(tools, "octop_thread_search", query="budget-token"))["threads"]
    }
    repos.thread_message_repo.mark_projection(own["thread_id"], "pending")
    assert own["thread_id"] not in {
        row["thread_id"]
        for row in (await call(tools, "octop_thread_search", query="budget-token"))["threads"]
    }
    assert (await call(tools, "octop_thread_read", thread_id=own["thread_id"]))[
        "history_status"
    ] == "pending"


async def test_history_marks_single_message_truncation(native: Any) -> None:
    _c, srv, _auth, _aid, _uid, tools = native
    tid = (await call(tools, "octop_thread_create"))["thread_id"]
    srv.services.thread_message_repo.replace_all(
        tid,
        [
            ThreadMessageInput(
                "long",
                "human",
                json.dumps({"type": "human", "data": {"content": "x" * 4001}}),
                1,
            )
        ],
    )
    history = await call(tools, "octop_thread_read", thread_id=tid)
    assert len(history["messages"][0]["text"]) == 4000
    assert history["text_truncated"] is True
    assert history["text_limits"] == {"per_message": 4000, "total": 24_000}


async def test_native_and_http_subagent_create_do_not_overwrite(
    native: Any, monkeypatch: Any
) -> None:
    c, srv, auth, aid, _uid, tools = native
    registry = srv.app_runtime.agent_registry
    workspace = registry.workspace_for_agent(aid)
    slug = "engineering-software-architect"
    first_read = asyncio.Event()
    release_read = asyncio.Event()
    second_attempt = asyncio.Event()
    original_read = workspace.aread_text
    original_lock = subagent_service._definition_lock
    attempts = 0

    async def gated_read(path: str, **kwargs: Any) -> Any:
        content = await original_read(path, **kwargs)
        if path == f"agents/{slug}.md" and not first_read.is_set():
            first_read.set()
            await release_read.wait()
        return content

    @asynccontextmanager
    async def observe_lock(agent_id: str, path: str) -> Any:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            second_attempt.set()
        async with original_lock(agent_id, path):
            yield

    monkeypatch.setattr(workspace, "aread_text", gated_read)
    monkeypatch.setattr(subagent_service, "_definition_lock", observe_lock)
    await registry._begin_invocation(aid)
    try:
        native_task = asyncio.create_task(
            call(
                tools,
                "octop_subagent_save",
                slug=slug,
                name="Native definition",
                description="Review",
                instructions="Retain this instruction.",
            )
        )
        await asyncio.wait_for(first_read.wait(), timeout=5)
        http_task = asyncio.create_task(
            c.post(
                f"/api/agents/{aid}/subagents/install",
                headers=auth,
                json={"slug": slug, "locale": "en"},
            )
        )
        await asyncio.wait_for(second_attempt.wait(), timeout=5)
        release_read.set()
        saved, rejected = await asyncio.gather(native_task, http_task)
        assert saved["saved"] is True
        assert rejected.status_code == 400
        assert "already exists" in rejected.text
        assert "Retain this instruction." in await original_read(f"agents/{slug}.md")
        assert asyncio.get_running_loop() not in subagent_service._WRITE_LOCKS
    finally:
        release_read.set()
        registry._end_invocation(aid)


async def test_self_reload_defers_and_coalesces_until_turn_release(
    native: Any, monkeypatch: Any
) -> None:
    _c, srv, _auth, aid, _uid, tools = native
    manager = srv.app_runtime.agent_registry
    reload = AsyncMock()
    monkeypatch.setattr(manager, "_reload_agent", reload)
    await manager._begin_invocation(aid)
    for description in ("First", "Second"):
        value = await call(tools, "octop_expert_update", description=description)
        assert value["reload_status"] == "pending_current_turn"
    await asyncio.sleep(0)
    reload.assert_not_awaited()
    assert manager.get_row(aid).description == "Second"
    manager._end_invocation(aid)
    await asyncio.sleep(0)
    reload.assert_awaited_once_with(aid)


async def test_device_selection_is_for_next_turn_and_preserves_context(native: Any) -> None:
    _c, srv, _auth, aid, uid, tools = native
    devices = srv.app_runtime.devices
    first = devices.enroll(
        owner_user_id=uid,
        name="First",
        platform="linux",
        capabilities=[],
        permissions=[],
        roots=[],
        trust_mode="owner",
    )["device"]["device_id"]
    second = devices.enroll(
        owner_user_id=uid,
        name="Second",
        platform="linux",
        capabilities=[],
        permissions=[],
        roots=[],
        trust_mode="owner",
    )["device"]["device_id"]
    tid = (await call(tools, "octop_thread_create"))["thread_id"]
    execution = srv.app_runtime.execution
    frozen = execution.resolve(
        uid, agent_id=aid, thread_id=tid, target_kind="device", device_id=first
    )
    token = var_child_runnable_config.set(
        {"configurable": {"user": uid, "octop_execution_context": frozen.public()}}
    )
    try:
        selected = await call(
            tools,
            "octop_device_select",
            thread_id=tid,
            target_kind="device",
            device_id=second,
            working_dir="research",
        )
    finally:
        var_child_runnable_config.reset(token)
    assert selected["effective"] == "next_turn"
    assert execution.get(uid, frozen.context_id).device_id == first
    assert execution.selection(uid, tid)["device_id"] == second
    assert execution.resolve(uid, agent_id=aid, thread_id=tid).device_id == second


async def test_0019_native_room_selection_and_shared_target_privacy(native: Any) -> None:
    c, srv, auth, aid, uid, tools = native
    repos, registry = srv.services.repos, srv.app_runtime.agent_registry
    devices, execution = srv.app_runtime.devices, srv.app_runtime.execution
    other = repos.user_repo.create(username="target-owner", password_hash="unused", role="user")
    first = devices.enroll(
        owner_user_id=uid,
        name="Owned default",
        platform="linux",
        capabilities=[],
        permissions=[],
        roots=[],
        trust_mode="owner",
    )["device"]["device_id"]
    second = devices.enroll(
        owner_user_id=uid,
        name="Room choice",
        platform="linux",
        capabilities=[],
        permissions=[],
        roots=[],
        trust_mode="owner",
    )["device"]["device_id"]
    private = devices.enroll(
        owner_user_id=other,
        name="PRIVATE_OWNER_DEVICE",
        platform="linux",
        capabilities=[],
        permissions=[],
        roots=[],
        trust_mode="owner",
    )["device"]["device_id"]
    current = registry.get_config(aid)
    current["device_binding"] = {"device_id": first, "working_dir": "owned-default"}
    repos.agent_repo.update_config(aid, config_json=json.dumps(current))
    repos.agent_repo.create(
        agent_id="shared-target-expert",
        user_id=other,
        name="Shared target expert",
        default_model="PRIVATE_PROVIDER/MODEL",
        config_json=json.dumps(
            {"device_binding": {"device_id": private, "working_dir": "PRIVATE_OWNER_DIRECTORY"}}
        ),
    )
    repos.agent_repo.set_shared("shared-target-expert", True)
    own_summary = await call(tools, "octop_expert_get", target_agent_id=aid)
    assert own_summary["default_target"]["device_id"] == first
    assert own_summary["default_target"]["device_name"] == "Owned default"
    shared = await call(tools, "octop_expert_get", target_agent_id="shared-target-expert")
    assert shared["default_target"] is None and shared["model_ref"] is None
    group = await call(
        tools, "octop_project_create", name="Device room", member_ids=[aid, "shared-target-expert"]
    )
    assert group["saved"] is True
    group_id, tid = group["agent_id"], group["thread_id"]
    http_group = (await c.get(f"/api/teams/{group_id}", headers=auth)).json()
    members = {row["agent_id"]: row for row in http_group["members"]}
    assert members[aid]["default_target"]["device_id"] == first
    assert members["shared-target-expert"]["default_target"] is None
    for payload in (shared, group, http_group, await call(tools, "octop_expert_list")):
        text = json.dumps(payload)
        assert private not in text and "PRIVATE_OWNER_DIRECTORY" not in text
        assert "PRIVATE_PROVIDER" not in text

    # Exercise the real Octop enrichment hook and the harness agent_list output boundary.
    from octop_harness.teams import tools as team_tools

    entry = SimpleNamespace(agent_id="shared-target-expert", metadata={})
    registry._refresh_peer_entry(entry)
    peer_team = SimpleNamespace(peer_display_name=lambda _entry: "Shared target expert")
    public = team_tools._agent_list_item(peer_team, entry, "en")
    assert public["default_target"] is None and public["model_ref"] is None
    owner_config = var_child_runnable_config.set({"configurable": {"user": other}})
    try:
        owner_view = team_tools._agent_list_item(peer_team, entry, "en")
        assert owner_view["default_target"]["device_id"] == private
    finally:
        var_child_runnable_config.reset(owner_config)

    shared_tid = (await call(tools, "octop_thread_create", target_agent_id="shared-target-expert"))[
        "thread_id"
    ]
    before_selection = execution.selection(uid, shared_tid)
    unsupported = await call(
        tools, "octop_device_select", thread_id=shared_tid, target_kind="device", device_id=second
    )
    assert "error" in unsupported
    assert execution.selection(uid, shared_tid) == before_selection
    before_bindings = {
        member: repos.agent_repo.get(member).config_json for member in [aid, "shared-target-expert"]
    }
    frozen = execution.resolve(
        uid, agent_id=group_id, thread_id=tid, target_kind="device", device_id=first
    )
    changed = await call(
        tools,
        "octop_device_select",
        thread_id=tid,
        target_kind="device",
        device_id=second,
        working_dir="room-choice",
    )
    assert changed["scope"] == "team_room" and changed["expert_defaults_unchanged"]
    assert execution.get(uid, frozen.context_id).device_id == first
    assert execution.resolve(uid, agent_id=group_id, thread_id=tid).device_id == second
    assert before_bindings == {
        member: repos.agent_repo.get(member).config_json for member in before_bindings
    }

    cleared = await call(tools, "octop_device_select", thread_id=tid, target_kind="device")
    assert cleared["selection"]["device_id"] is None
    assert before_bindings == {
        member: repos.agent_repo.get(member).config_json for member in before_bindings
    }


async def test_shared_team_async_tool_dispatch_rechecks_current_roster(native: Any) -> None:
    from unittest.mock import MagicMock

    from octop_harness.teams.team_manager import TeamManager
    from octop_harness.teams.tools import build_team_tools

    from octop.infra.agents.teams.shared_peers import install_shared_team_peers

    _c, srv, _auth, aid, uid, tools = native
    repos, manager = srv.services.repos, srv.app_runtime.agent_registry
    foreign = repos.user_repo.create(
        username="shared-dispatch-owner", password_hash="h", role="user"
    )
    for target in ("invited-shared", "outside-shared", "private-expert"):
        repos.agent_repo.create(agent_id=target, user_id=foreign, name=target)
        repos.agent_repo.set_shared(target, target != "private-expert")
    project = await call(
        tools,
        "octop_project_create",
        name="Shared dispatch room",
        member_ids=[aid, "invited-shared"],
    )
    host_id, tid = project["agent_id"], project["thread_id"]
    entries = {
        target: SimpleNamespace(
            agent_id=target,
            metadata={"user_id": owner, "display_name": target},
            config=SimpleNamespace(
                name=target,
                team_peers=(aid, "invited-shared") if target == host_id else None,
                language="en",
                peer_invoke_mode="async",
            ),
        )
        for target, owner in [
            (host_id, uid),
            (aid, uid),
            ("invited-shared", foreign),
            ("outside-shared", foreign),
            ("private-expert", foreign),
        ]
    }
    team = TeamManager(
        SimpleNamespace(list=lambda: list(entries.values()), get=lambda target: entries[target])
    )
    team._inbox = SimpleNamespace(enqueue=MagicMock(return_value="queued-shared"))
    from dataclasses import asdict

    from langchain.agents.middleware import ModelRequest
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    from langchain_core.messages import SystemMessage

    from octop.infra.agents.middleware.device_target import DeviceTargetMiddleware
    from octop.infra.errors import OctopError

    private_device = srv.app_runtime.devices.enroll(
        owner_user_id=foreign,
        name="Private",
        platform="linux",
        capabilities=[],
        permissions=[],
        roots=[],
        trust_mode="owner",
    )["device"]["device_id"]
    caller_device = srv.app_runtime.devices.enroll(
        owner_user_id=uid,
        name="Caller",
        platform="linux",
        capabilities=[],
        permissions=[],
        roots=[],
        trust_mode="owner",
    )["device"]["device_id"]
    repos.agent_repo.update_config(
        "invited-shared",
        config_json=json.dumps(
            {
                "device_binding": {
                    "device_id": private_device,
                    "working_dir": "PRIVATE_DEFAULT_DIRECTORY",
                }
            }
        ),
    )
    srv.app_runtime.execution.save_default_target(uid, caller_device, "CALLER_DEFAULT_DIRECTORY")
    prepared_requests = []

    async def actual_preparation(target_id: str, request: Any) -> dict[str, Any]:
        prepared = manager._prepare_stream_request(target_id, asdict(request))
        prepared_requests.append(prepared)
        assert prepared["conversation_mode"] == "ask"
        assert prepared["skills"] == [] and prepared["mcp_servers"] == []
        assert "octop_execution_context" not in prepared["configurable"]
        assert "octop_device_target" not in prepared["configurable"]
        cfg = {**prepared["configurable"], "user": uid, "agent_id": target_id}
        scope = var_child_runnable_config.set({"configurable": cfg})
        try:
            middleware = DeviceTargetMiddleware(
                srv.app_runtime.devices,
                private_device,
                None,
                shared_text_manager=manager,
                agent_id=target_id,
            )
            model_request = ModelRequest(
                model=FakeListChatModel(responses=["ok"]),
                messages=[],
                system_message=SystemMessage(content="existing rules"),
                tools=["execute", "device_call", "ask_agent"],
            )
            observed = []

            async def inspect_request(value: Any) -> Any:
                observed.append(value)
                return value

            await middleware.awrap_model_call(model_request, inspect_request)
            sanitized = observed[0]
            assert sanitized.tools == []
            assert "PRIVATE_DEFAULT_DIRECTORY" not in sanitized.system_message.content
            assert private_device not in sanitized.system_message.content
        finally:
            var_child_runnable_config.reset(scope)
        return {"response": "shared text result"}

    target_calls = AsyncMock(side_effect=actual_preparation)
    team._call_agent = target_calls
    team.bind_peer_enrich(manager._refresh_peer_entry)
    install_shared_team_peers(manager, team)
    from octop.infra.agents.teams.collaboration import CollaborationService
    from octop.infra.agents.teams.team_manager import TeamManager as ApplicationTeam

    room = ApplicationTeam(
        agent_manager=manager,
        thread_registry=srv.app_runtime.gateway.thread_registry,
        user_repo=repos.user_repo,
        thread_message_repo=repos.thread_message_repo,
    )
    team.bind_peer_session(
        prepare=room.prepare_peer_session,
        after=room.record_peer_turn,
        lifecycle=CollaborationService(manager).lifecycle,
    )
    ask = next(
        tool
        for tool in build_team_tools(team, peer_invoke_mode="async")
        if tool.name == "ask_agent"
    )
    token = var_child_runnable_config.set(
        {"configurable": {"user": uid, "agent_id": host_id, "thread_id": tid}}
    )
    try:
        accepted = json.loads(
            await ask.ainvoke({"expert": "invited-shared", "message": "Review this text"})
        )
        assert accepted["job_id"] == "queued-shared", accepted
        from octop_harness.teams.inbox import InboxMessage

        queued = team._inbox.enqueue.call_args.kwargs
        msg = InboxMessage(
            id=accepted["job_id"],
            **{key: value for key, value in queued.items() if key not in {"inbox_id", "job_id"}},
        )
        await team._invoke_inbox_target(msg)
        target_calls.assert_awaited_once()
        forged = {
            **prepared_requests[0],
            "configurable": {
                **prepared_requests[0]["configurable"],
                "octop_shared_text_scope": {
                    "owner": uid,
                    "host": host_id,
                    "target": "invited-shared",
                    "thread": tid,
                    "signature": "forged",
                },
            },
        }
        with pytest.raises(OctopError, match="provenance"):
            manager._prepare_stream_request("invited-shared", forged)
        assert entries["invited-shared"].metadata["user_id"] == foreign
        for query in ("outside-shared", "private-expert"):
            denied = json.loads(await ask.ainvoke({"expert": query, "message": "denied"}))
            assert "error" in denied
        for state in ("disabled", "unshared", "removed"):
            if state == "disabled":
                repos.agent_repo.set_enabled("invited-shared", False)
            elif state == "unshared":
                repos.agent_repo.set_enabled("invited-shared", True)
                repos.agent_repo.set_shared("invited-shared", False)
            else:
                repos.agent_repo.set_shared("invited-shared", True)
                manager.teams.replace_members(host_id, [aid, "outside-shared"])
            denied = json.loads(
                await ask.ainvoke({"expert": "invited-shared", "message": "denied"})
            )
            assert "error" in denied
            with pytest.raises(ValueError, match="enabled member"):
                await team._invoke_inbox_target(msg)
            with pytest.raises(OctopError, match="no longer authorized"):
                manager._prepare_stream_request("invited-shared", prepared_requests[0])
        target_calls.assert_awaited_once()
    finally:
        var_child_runnable_config.reset(token)


async def test_discovery_only_announces_registered_tools_and_safe_reference_ids(
    native: Any,
) -> None:
    _c, srv, _auth, aid, _uid, tools = native
    registry = srv.app_runtime.agent_registry
    runtime = registry.get_agent(aid)
    runtime.config.tools = registry._build_harness_config(registry.get_row(aid)).tools
    runtime.config.tools_disabled = frozenset({"octop_expert_create"})
    capabilities = await call(tools, "octop_capabilities")
    names = {entry["name"] for entry in capabilities["tools"]}
    assert "octop_expert_create" not in names
    assert "octop_project_update_members" in names
    assert "task_board_create" in capabilities["existing_tools"]
    assert "schedule_self_check" in capabilities["existing_tools"]
    refs = await call(tools, "octop_resource_list")
    assert "models" in refs and "tools" in refs
    assert "sk-" not in json.dumps(refs)


async def test_group_reports_created_resource_if_conversation_insert_fails(
    native: Any, monkeypatch: Any
) -> None:
    _c, srv, _auth, aid, _uid, tools = native
    second = await call(tools, "octop_expert_create", name="Second for partial group")

    def broken_insert(**_kwargs: Any) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(srv.services.thread_repo, "insert", broken_insert)
    result = await call(
        tools, "octop_project_create", name="Created group", member_ids=[aid, second["agent_id"]]
    )
    assert result["saved"] is True and result["thread_created"] is False
    assert result["next_action"] == "octop_thread_create"
    assert srv.app_runtime.agent_registry.get_row(result["agent_id"]).kind == "team"


def test_host_native_allowlist_keeps_file_and_shell_denied() -> None:
    assert set(NATIVE_TOOL_NAMES) <= HOST_TOOLS_ALLOWED
    assert {"execute", "read_file", "write_file", "browser_use"} <= HOST_TOOLS_DISABLED
