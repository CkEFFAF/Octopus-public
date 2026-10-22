"""Native extensions use authenticated identity and real Dashboard-visible storage."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zipfile import ZipFile

import pytest
from langchain_core.tools import StructuredTool
from langgraph.config import var_child_runnable_config
from pydantic import ValidationError

from octop.infra.agents.middleware.live_configuration import LiveConfigurationMiddleware
from octop.infra.agents.native_management_tools import build_native_management_tools
from tests.integration.test_native_management_tools import call
from tests.integration.test_native_management_tools import native as native

MAIL = {
    "email": "student@university.example",
    "password": "synthetic-app-password-123",
    "mail_provider": "custom",
    "imap_host": "imap.university.example",
    "imap_port": 1993,
    "smtp_host": "smtp.university.example",
    "smtp_port": 465,
}


async def create_mail(tools):
    result = await call(
        tools,
        "octop_connector_create",
        kind="qq-mail",
        display_name="University mail",
        credentials=MAIL,
    )
    assert result.get("saved"), result
    return result


async def test_repeated_native_builds_keep_expert_closures_and_strict_arguments(native):
    _client, srv, _auth, aid, _uid, tools = native
    created = await call(tools, "octop_expert_create", name="Second tool binding")
    other_id = created["agent_id"]
    other_tools = {
        tool.name: tool
        for tool in build_native_management_tools(
            srv.app_runtime.agent_registry, srv.services.repos, other_id
        )
    }
    assert (await call(tools, "octop_expert_get"))["agent_id"] == aid
    assert (await call(other_tools, "octop_expert_get"))["agent_id"] == other_id
    with pytest.raises(ValidationError):
        await other_tools["octop_connector_create"].ainvoke(
            {
                "kind": "qq-mail",
                "display_name": "Invalid override",
                "credentials": MAIL,
                "user_id": _uid,
            }
        )


async def test_ordinary_user_create_rotate_test_and_http_preview(native, monkeypatch):
    client, srv, auth, aid, uid, tools = native
    repos = srv.services.repos
    repos.user_repo.set_role(uid, "user")
    repos.user_repo.set_permissions(uid, ["connectors"])
    catalog = await call(tools, "octop_connector_catalog", kind="qq-mail")
    assert catalog["can_manage"]
    assert any(field["key"] == "smtp_port" for field in catalog["catalog"][0]["credential_fields"])
    created = await create_mail(tools)
    iid = created["instance_id"]
    assert created["authentication_verified"] is False
    assert not created["shared"] and not created["default_open"]
    row = repos.connector_repo.get(iid)
    assert MAIL["password"].encode() not in row.credential_blob
    response = await client.get(f"/api/connector-instances/{iid}", headers=auth)
    assert response.status_code == 200
    preview = response.json()["credentials_preview"]
    assert preview["smtp_port"] == 465 and preview["imap_port"] == 1993
    got = await call(tools, "octop_connector_get", instance_id=iid)
    assert got["settings"]["imap_host"] == MAIL["imap_host"]
    assert "password" in got["configured_secret_fields"]
    assert MAIL["password"] not in json.dumps(got)

    failed = await call(
        tools,
        "octop_connector_update",
        instance_id=iid,
        display_name="Must not persist",
        credentials={"smtp_port": 70000},
    )
    assert "error" in failed
    assert repos.connector_repo.get(iid).display_name == row.display_name
    assert repos.connector_repo.get(iid).credential_blob == row.credential_blob
    rotated = await call(
        tools, "octop_connector_update", instance_id=iid, credentials={"password": "rotated-secret"}
    )
    assert rotated["saved"]
    svc = srv.app_runtime.agent_registry._connector_svc
    assert svc.decrypt(iid)["password"] == "rotated-secret"
    probe = AsyncMock(
        return_value={
            "ok": False,
            "error": "upstream echoed rotated-secret",
            "password": "rotated-secret",
        }
    )
    monkeypatch.setattr("octop.infra.connectors.probe.probe_connector", probe)
    tested = await call(tools, "octop_connector_test", instance_id=iid)
    assert tested["ok"] is False and "rotated-secret" not in json.dumps(tested)
    assert probe.await_count == 1
    assert all(
        "rotated-secret" not in audit.payload
        for audit in repos.audit_repo.query(action="octop_connector_update")
    )
    repos.user_repo.set_permissions(uid, [])
    assert "error" in await call(
        tools, "octop_connector_update", instance_id=iid, status="disabled"
    )
    assert repos.connector_repo.get(iid).status == "active"
    with pytest.raises(ValidationError):
        await tools["octop_connector_create"].ainvoke(
            {"kind": "qq-mail", "display_name": "other", "credentials": MAIL, "user_id": uid}
        )


@pytest.mark.parametrize("mode", ["ask", "plan", "shared", "disabled", "tool_disabled"])
async def test_extension_write_guards(native, mode):
    _c, srv, _auth, aid, uid, tools = native
    manager = srv.app_runtime.agent_registry
    cfg = {"user": uid, "work_mode": mode if mode in {"ask", "plan"} else "agentic"}
    if mode == "shared":
        cfg["octop_shared_text_scope"] = {}
    if mode == "disabled":
        srv.services.repos.user_repo.set_disabled(uid, True)
    if mode == "tool_disabled":
        await manager.persist_tools_disabled(
            aid, {"octop_mcp_upsert", "octop_skill_save", "octop_connector_create"}
        )
    token = var_child_runnable_config.set({"configurable": cfg})
    try:
        assert "error" in await call(
            tools, "octop_connector_create", kind="qq-mail", display_name="Denied", credentials=MAIL
        )
        assert "error" in await call(
            tools,
            "octop_mcp_upsert",
            name="denied",
            server={"transport": "stdio", "command": "unused"},
        )
        assert "error" in await call(
            tools,
            "octop_skill_save",
            slug="denied",
            content="---\nname: denied\ndescription: denied\n---\n",
        )
        assert srv.services.repos.connector_repo.list_by_user(uid) == []
    finally:
        var_child_runnable_config.reset(token)


async def test_foreign_shared_connection_visible_but_not_writable_even_to_admin(native):
    _c, srv, _auth, _aid, uid, tools = native
    repos = srv.services.repos
    other = repos.user_repo.create(username="mail-owner", password_hash="h", role="user")
    svc = srv.app_runtime.agent_registry._connector_svc
    row = await svc.create_instance(
        other, kind="qq-mail", display_name="Shared mail", credentials=MAIL, shared=True
    )
    listed = await call(tools, "octop_connector_list")
    assert any(
        item["instance_id"] == row.instance_id and not item["writable"]
        for item in listed["instances"]
    )
    for name in ("octop_connector_get", "octop_connector_update", "octop_connector_test"):
        args = {"instance_id": row.instance_id}
        if name.endswith("update"):
            args["status"] = "disabled"
        assert "error" in await call(tools, name, **args)
    assert repos.connector_repo.get(row.instance_id).status == "active"
    assert uid != other
    repos.agent_repo.create(agent_id="foreign-extension-expert", user_id=other, name="Foreign")
    for tool_name, arguments in (
        ("octop_skill_save", {"slug": "foreign", "content": "Denied"}),
        ("octop_skill_install", {"skill_slug": "foreign"}),
        ("octop_tool_set_enabled", {"name": "execute", "enabled": False}),
        ("octop_plugin_set_enabled", {"plugin_id": "foreign", "enabled": True}),
    ):
        assert "error" in await call(
            tools, tool_name, target_agent_id="foreign-extension-expert", **arguments
        )


async def test_attach_builtin_and_custom_preserves_turn_selection_and_device_policy(
    native, monkeypatch
):
    _c, srv, _auth, aid, uid, tools = native
    manager = srv.app_runtime.agent_registry
    row = await create_mail(tools)
    custom = await call(
        tools,
        "octop_mcp_upsert",
        name="research",
        server={
            "transport": "streamable_http",
            "url": "https://mcp.example.com/endpoint",
            "headers": {"Authorization": "Bearer synthetic-token"},
        },
    )
    assert custom.get("saved"), custom
    cfg = {
        "user": uid,
        "agent_id": aid,
        "work_mode": "agentic",
        "thread_id": "thread-now",
        "octop_task_run_id": "run-now",
        "mcp_servers": ["research"],
    }
    token = var_child_runnable_config.set({"configurable": cfg})
    try:
        monkeypatch.setattr(manager, "is_agent_active", lambda target: True)
        attached = await call(tools, "octop_connector_attach", instance_id=row["instance_id"])
        names = ["research", row["mcp_server_name"]]
        assert attached.get("current_conversation_update", {}).get("mcp_servers") == names, attached
        assert LiveConfigurationMiddleware(manager, aid)._selection(cfg) == names
        again = await call(tools, "octop_connector_attach", instance_id=custom["instance_id"])
        assert again["mcp_servers"] == names
        synthetic = StructuredTool.from_function(
            lambda: "synthetic", name="research_tool", description="Synthetic MCP tool"
        )
        loader = AsyncMock(return_value=[synthetic])
        monkeypatch.setattr(manager, "_get_or_load_mcp_tools", loader)
        loaded = await LiveConfigurationMiddleware(manager, aid)._tools(cfg)
        assert "research_tool" in {tool.name for tool in loaded}
        loader.assert_awaited()
        monkeypatch.setattr(
            manager,
            "device_mcp_pack_for_turn",
            lambda *args, **kwargs: ([], [row["mcp_server_name"]], None),
        )
        denied = await call(tools, "octop_connector_attach", instance_id=row["instance_id"])
        assert "error" in denied
        assert json.loads(manager.get_row(aid).mcp_servers) == names
    finally:
        var_child_runnable_config.reset(token)


async def test_custom_mcp_merge_validation_secrets_and_probe(native, monkeypatch):
    client, srv, auth, _aid, uid, tools = native
    srv.services.repos.user_repo.set_role(uid, "user")
    srv.services.repos.user_repo.set_permissions(uid, ["connectors"])
    server = {
        "transport": "stdio",
        "command": "synthetic-server",
        "args": ["--token=argument-secret"],
        "env": {"API_KEY": "environment-secret"},
    }
    created = await call(tools, "octop_mcp_upsert", name="local", server=server)
    assert created.get("saved"), created
    assert "error" in await call(tools, "octop_mcp_upsert", name="local", server={"enabled": False})
    assert (
        await call(
            tools,
            "octop_mcp_upsert",
            name="other",
            server={"transport": "streamable_http", "url": "https://mcp.example.com/api"},
        )
    )["saved"]
    assert (
        await call(
            tools,
            "octop_mcp_upsert",
            name="local",
            server={"display_name": "Local tools"},
            overwrite=True,
        )
    )["saved"]
    svc = srv.app_runtime.agent_registry._connector_svc
    before = svc.get_custom_servers(uid)
    assert before["local"]["env"] == server["env"] and "other" in before
    assert "error" in await call(
        tools,
        "octop_mcp_upsert",
        name="local",
        server={"command": "different-server"},
        overwrite=True,
    )
    assert "error" in await call(
        tools,
        "octop_mcp_upsert",
        name="other",
        server={"oauth": {"access_token": "not-a-consent-flow"}},
        overwrite=True,
    )
    assert svc.get_custom_servers(uid) == before
    assert "error" in await call(tools, "octop_mcp_upsert", name="bad/name", server=server)
    assert svc.get_custom_servers(uid) == before
    listed = await call(tools, "octop_mcp_list")
    assert "environment-secret" not in json.dumps(listed) and "argument-secret" not in json.dumps(
        listed
    )
    probe = AsyncMock(
        return_value={
            "ok": False,
            "error": "environment-secret --token=argument-secret",
            "tools": [],
        }
    )
    monkeypatch.setattr("octop.infra.agents.native_extension_tools.probe_custom_mcp_server", probe)
    result = await call(tools, "octop_mcp_test", name="local")
    assert (
        result["ok"] is False
        and "environment-secret" not in json.dumps(result)
        and "argument-secret" not in json.dumps(result)
    )
    response = await client.get("/api/connectors/custom-mcp", headers=auth)
    assert response.status_code == 200
    assert set(response.json()["servers"]) == {"local", "other"}


async def test_skill_author_install_toggle_validation_and_http_visibility(native, monkeypatch):
    client, srv, auth, aid, _uid, tools = native
    manager = srv.app_runtime.agent_registry
    manifest = (
        "---\nname: Study helper\ndescription: Synthetic study guidance\n---\nRead the sources.\n"
    )
    save = await call(
        tools,
        "octop_skill_save",
        slug="study-helper",
        content=manifest,
        files={"references/example.txt": "Synthetic reference"},
        enabled=False,
    )
    assert save.get("saved"), save
    assert save["reload_status"] == "not_required"
    skills = (await client.get(f"/api/agents/{aid}/skills", headers=auth)).json()
    item = next(item for item in skills if item["slug"] == "study-helper")
    assert item["enabled"] is False
    workspace = manager.get_agent(aid).workspace
    assert (
        await workspace.aread_text("skills/study-helper/references/example.txt")
        == "Synthetic reference"
    )
    assert "error" in await call(tools, "octop_skill_save", slug="study-helper", content=manifest)
    assert "error" in await call(
        tools, "octop_skill_save", slug="bad", content=manifest, files={"../escape.txt": "Denied"}
    )
    assert await workspace.aread_text("skills/bad/SKILL.md") is None
    enabled = await call(tools, "octop_skill_set_enabled", slug="study-helper", enabled=True)
    assert enabled["saved"]
    assert "Study helper" not in manager.get_config(aid)["skills_disabled"]
    live = LiveConfigurationMiddleware(manager, aid)
    assert "study-helper" in {
        item["slug"] for item in await live._skills({"user": _uid, "work_mode": "agentic"})
    }
    assert await live._skills({"user": _uid, "work_mode": "agentic", "skills": []}) == []
    downloaded = AsyncMock(return_value=[("SKILL.md", manifest.encode())])
    monkeypatch.setattr(
        "octop.infra.agents.native_extension_tools.download_skillhub_package", downloaded
    )
    installed = await call(tools, "octop_skill_install", skill_slug="downloaded", enabled=False)
    assert installed.get("saved"), installed
    assert "downloaded" in manager.get_config(aid)["skills_disabled"]
    assert "error" in await call(
        tools, "octop_skill_install", skill_slug="downloaded", url="https://example.com/archive.zip"
    )
    summaries = await manager.list_skill_summaries(aid)
    monkeypatch.setattr(
        manager,
        "list_skill_summaries",
        AsyncMock(return_value=[*summaries, {"slug": "protected", "kind": "package"}]),
    )
    assert "error" in await call(
        tools, "octop_skill_save", slug="protected", content=manifest, overwrite=True
    )
    assert await workspace.aread_text("skills/protected/SKILL.md") is None


async def test_native_plugin_url_installs_real_synthetic_package_without_active_reload(
    native, monkeypatch
):
    from octop_harness.plugins import PluginRegistry

    client, srv, auth, aid, _uid, tools = native
    manager = srv.app_runtime.agent_registry
    fixture = Path(__file__).resolve().parents[1] / "fixtures/plugins/echo-tool"

    def download(url, target):
        assert url == "https://plugins.example.test/echo.zip"
        with ZipFile(target, "w") as archive:
            for path in fixture.iterdir():
                if path.is_file():
                    archive.write(path, f"echo-tool/{path.name}")

    monkeypatch.setattr("octop.infra.agents.plugins.manager.urllib.request.urlretrieve", download)
    schedule = Mock()
    monkeypatch.setattr(manager, "schedule_reload", schedule)
    monkeypatch.setattr(manager, "is_agent_active", lambda target: True)
    try:
        result = await call(
            tools, "octop_plugin_install", url="https://plugins.example.test/echo.zip"
        )
        assert result.get("saved"), result
        assert result["plugin_id"] == "echo-tool" and result["effective"] == "after_current_turn"
        assert schedule.called
        response = await client.get("/api/plugins", headers=auth)
        assert any(item["id"] == "echo-tool" for item in response.json())
        listed = await call(tools, "octop_tool_list")
        assert any(item["plugin_id"] == "echo-tool" for item in listed["plugin_tools"])
    finally:
        PluginRegistry.reset()


async def test_tools_and_plugin_install_permissions_preserve_settings_defer_reload(
    native, monkeypatch
):
    _c, srv, _auth, aid, uid, tools = native
    manager = srv.app_runtime.agent_registry
    plugin = {
        "id": "synthetic",
        "enabled": True,
        "tools": [{"name": "calculate"}, {"name": "inspect"}],
    }
    mgr = SimpleNamespace(
        list_installed=lambda: [plugin],
        list_market=lambda: [plugin],
        global_enabled_map=lambda: {"synthetic": True},
        install_from_market=Mock(
            return_value=SimpleNamespace(manifest=SimpleNamespace(id="synthetic", version="1.0"))
        ),
    )
    monkeypatch.setattr(manager, "_plugin_manager", mgr)
    reload = Mock()
    monkeypatch.setattr(manager, "schedule_reload", reload)
    monkeypatch.setattr(manager, "is_agent_active", lambda target: True)
    assert "error" in await call(tools, "octop_tool_set_enabled", name="read_file", enabled=False)
    assert (await call(tools, "octop_tool_set_enabled", name="execute", enabled=False))["saved"]
    assert "execute" in manager.get_config(aid)["tools_disabled"]
    await call(
        tools, "octop_tool_set_enabled", name="inspect", plugin_id="synthetic", enabled=False
    )
    await call(
        tools, "octop_tool_set_enabled", name="calculate", plugin_id="synthetic", enabled=True
    )
    assert manager.get_config(aid)["plugins"]["synthetic"]["tools"]["inspect"]["enabled"] is False
    state = await call(tools, "octop_plugin_set_enabled", plugin_id="synthetic", enabled=False)
    assert (
        state["effective"] == "after_current_turn"
        and state["reload_status"] == "pending_current_turn"
    )
    assert manager.get_config(aid)["plugins"]["synthetic"]["tools"]["calculate"]["enabled"] is True
    srv.services.repos.user_repo.set_role(uid, "user")
    srv.services.repos.user_repo.set_permissions(uid, ["connectors"])
    assert "error" in await call(tools, "octop_plugin_install", plugin_id="synthetic")
    mgr.install_from_market.assert_not_called()
    srv.services.repos.user_repo.set_permissions(uid, ["plugins"])
    result = await call(tools, "octop_plugin_install", plugin_id="synthetic")
    assert result.get("saved"), result
    assert result["effective"] == "after_current_turn"
    assert reload.called
