"""Sharing freezes canonical history with strict ownership and public boundaries."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.config import var_child_runnable_config
from tests.unit.agents.test_collaboration_resources import rig as rig

from octop.api.app import _install_exception_handlers
from octop.api.deps import get_server, sign_token
from octop.api.middleware.jwt_auth import install
from octop.api.routers.chat.shares import router
from octop.config import OctopConfig, load_config, validate_public_origin
from octop.infra.agents.native_management_tools import build_native_management_tools
from octop.infra.agents.settings.tool_catalog import NATIVE_TOOL_NAMES
from octop.infra.agents.teams.service import HOST_TOOLS_ALLOWED
from octop.infra.errors import OctopError
from octop.infra.history.projection import message_inputs
from octop.infra.history.service import HistoryArchive
from octop.infra.history.sharing import ThreadSharingService, public_text
from octop.infra.history.store import HistoryStore
from octop.infra.users.preferences import SIDEBAR_NAV_KEYS
from octop.infra.utils.log_redaction import QuerySecretFilter


@pytest.fixture
def sharing(rig, tmp_path):
    store = HistoryStore(tmp_path / "archive.db", identity="sharing")
    archive = HistoryArchive(store, rig.repos.thread_message_repo, rig.repos.trajectory_event_repo)
    rig.manager.get_row = rig.repos.agent_repo.get
    rig.manager.get_config = lambda _: {"tools_disabled": []}
    config = OctopConfig(public_origin="https://share.example.com")
    service = ThreadSharingService(rig.repos, config, rig.manager, archive)
    rig.repos.thread_message_repo.replace_all(
        "root",
        message_inputs(
            [
                HumanMessage(
                    content="Question\n\n[Attachment] internal-resource-id@version\nprivate-path"
                ),
                AIMessage(
                    content=[
                        {"type": "text", "text": "Answer"},
                        {"type": "thinking", "thinking": "PRIVATE_THOUGHT"},
                    ],
                    additional_kwargs={"reasoning_content": "PRIVATE_REASONING"},
                ),
                AIMessage(content="Answer"),
                ToolMessage(content="PRIVATE_TOOL_BODY", tool_call_id="x"),
                SystemMessage(content="PRIVATE_SYSTEM"),
            ]
        ),
    )
    yield service
    store.close()


@pytest.mark.asyncio
async def test_frozen_snapshot_recopy_stale_expiry_revoke_deletion(sharing, rig):
    preview = await sharing.preview(rig.owner, "root")
    assert [(m["id"], m["role"], m["content"]) for m in preview["messages"]] == [
        (1, "user", "Question"),
        (2, "assistant", "Answer"),
        (3, "assistant", "Answer"),
    ]
    assert (await sharing.preview(rig.owner, "root"))["preview_digest"] == preview["preview_digest"]
    created = await sharing.create(rig.owner, "root", preview["preview_digest"], None)
    token = created["public_path"].rsplit("/", 1)[1]
    assert created["public_url"] == "https://share.example.com/share/" + token
    row = rig.repos.thread_share_repo.owned(rig.owner, created["share_id"])
    assert token not in json.dumps(row)
    assert sharing.list(rig.owner)["shares"][0]["public_url"] == created["public_url"]
    frozen = sharing.public(token)
    assert set(frozen) == {"title", "timezone", "messages", "created_at", "expires_at"}
    rig.repos.thread_message_repo.append_if_ready(
        "root", message_inputs([AIMessage(content="New private text")])
    )
    assert sharing.public(token) == frozen
    with pytest.raises(OctopError, match="Preview changed") as err:
        await sharing.create(rig.owner, "root", preview["preview_digest"])
    assert err.value.status == 409
    assert len(sharing.list(rig.owner)["shares"]) == 1
    for owner in (rig.outsider,):
        assert sharing.list(owner)["shares"] == []
        with pytest.raises(OctopError):
            sharing.revoke(owner, created["share_id"])
        with pytest.raises(OctopError):
            await sharing.preview(owner, "root")
    sharing.revoke(rig.owner, created["share_id"])
    sharing.revoke(rig.owner, created["share_id"])
    inactive = sharing.list(rig.owner)["shares"][0]
    assert inactive["status"] == "revoked" and inactive["public_url"] is None
    assert (
        rig.repos.thread_share_repo.owned(rig.owner, created["share_id"])["encrypted_token"] is None
    )
    with pytest.raises(OctopError) as err:
        sharing.public(token)
    assert err.value.status == 404
    preview = await sharing.preview(rig.owner, "root")
    other = await sharing.create(rig.owner, "root", preview["preview_digest"], 60)
    token = other["public_path"].rsplit("/", 1)[1]
    with rig.repos.db.connect() as conn:
        conn.execute("UPDATE thread_shares SET expires_at=0 WHERE share_id=?", (other["share_id"],))
    with pytest.raises(OctopError):
        sharing.public(token)
    assert sharing.list(rig.owner)["shares"][0]["status"] == "expired"
    with rig.repos.db.connect() as conn:
        conn.execute("DELETE FROM threads WHERE thread_id='root'")
        assert conn.execute("SELECT COUNT(*) FROM thread_shares").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_owner_paging_and_disabled_owner(sharing, rig):
    preview = await sharing.preview(rig.owner, "root")
    records = [await sharing.create(rig.owner, "root", preview["preview_digest"]) for _ in range(4)]
    first = sharing.list(rig.owner, limit=2)
    second = sharing.list(rig.owner, limit=2, before=first["next_before"])
    assert [r["share_id"] for r in first["shares"] + second["shares"]] == [
        r["share_id"] for r in reversed(records)
    ]
    assert first["has_more"] and not second["has_more"]
    for cursor in ("0", "-1", "not-a-cursor", "9" * 50):
        with pytest.raises(OctopError):
            sharing.list(rig.owner, before=cursor)
    with rig.repos.db.connect() as conn:
        conn.execute("UPDATE users SET disabled=1 WHERE id=?", (rig.owner,))
    with pytest.raises(OctopError) as err:
        sharing.public(records[0]["public_path"].split("/")[-1])
    assert err.value.status == 404


@pytest.mark.asyncio
async def test_source_public_bytes_and_empty_limits(sharing, rig, monkeypatch):
    for constant in ("MAX_SOURCE_MESSAGES", "MAX_PUBLIC_MESSAGES", "MAX_SNAPSHOT_BYTES"):
        with monkeypatch.context() as patch:
            patch.setattr("octop.infra.history.sharing." + constant, 1)
            with pytest.raises(OctopError) as err:
                await sharing.preview(rig.owner, "root")
            assert err.value.status == 413
    rig.repos.thread_message_repo.replace_all(
        "root", message_inputs([ToolMessage(content="hidden", tool_call_id="x")])
    )
    with pytest.raises(OctopError) as err:
        await sharing.preview(rig.owner, "root")
    assert err.value.code == "SHARE_INVALID"


@pytest.mark.asyncio
async def test_invalid_wire_roles_are_not_published(sharing, rig, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "octop.infra.history.sharing.read_page",
        AsyncMock(
            return_value={
                "messages": [
                    {"type": [], "data": {"content": "hidden"}},
                    {"type": {"role": "assistant"}, "data": {"content": "hidden"}},
                    {"data": {"content": "hidden"}},
                    {"type": "human", "data": {"content": "public text"}},
                ],
                "has_more": False,
                "next_cursor": None,
            }
        ),
    )
    preview = await sharing.preview(rig.owner, "root")
    assert preview["messages"] == [{"id": 1, "role": "user", "content": "public text"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("archive_enabled", [False, True])
async def test_legacy_checkpoint_and_archive_upper_bound(sharing, rig, archive_enabled):
    from unittest.mock import AsyncMock

    if not archive_enabled:
        sharing.archive = None
    rig.repos.thread_repo.insert(
        thread_id="old",
        agent_id="parent",
        user_id=rig.owner,
        channel_type="dashboard",
        session_key="old",
    )
    rig.repos.thread_message_repo.mark_projection("old", "pending")
    state = SimpleNamespace(
        values={
            "messages": [
                HumanMessage(content="Legacy question"),
                AIMessage(content="Legacy answer"),
            ]
        },
        config={"configurable": {"thread_id": "old", "checkpoint_id": "pinned"}},
    )
    rig.manager.get_agent = lambda _: SimpleNamespace(
        graph=SimpleNamespace(aget_state=AsyncMock(return_value=state))
    )
    assert [m["content"] for m in (await sharing.preview(rig.owner, "old"))["messages"]] == [
        "Legacy question",
        "Legacy answer",
    ]
    # A ready canonical projection remains independent of checkpoint availability.
    assert (await sharing.preview(rig.owner, "root"))["message_count"] == 3


@pytest.mark.asyncio
async def test_v2_archive_scan_is_pinned_when_new_messages_arrive(sharing, rig, monkeypatch):
    from langchain_core.messages import message_to_dict

    from octop.infra.history import sharing as module

    sharing.archive.enabled = True
    turn = sharing.archive.begin("parent", "root")
    sharing.archive.save_messages(
        turn, [message_to_dict(AIMessage(content=f"item-{i}")) for i in range(210)]
    )
    sharing.archive.finish(turn["id"], "completed")
    actual = module.read_page
    calls = 0

    async def append_after_first(*args, **kwargs):
        nonlocal calls
        result = await actual(*args, **kwargs)
        calls += 1
        if calls == 1:
            later = sharing.archive.begin("parent", "root")
            sharing.archive.save_messages(
                later, [message_to_dict(AIMessage(content="PRIVATE_AFTER_BOUNDARY"))]
            )
            sharing.archive.finish(later["id"], "completed")
        return result

    monkeypatch.setattr(module, "read_page", append_after_first)
    preview = await sharing.preview(rig.owner, "root")
    assert calls == 2 and preview["message_count"] == 213
    assert "PRIVATE_AFTER_BOUNDARY" not in json.dumps(preview)
    assert preview["messages"][-1]["content"] == "item-209"


@pytest.mark.asyncio
async def test_unconfigured_origin_keeps_preview_list_revoke_available(sharing, rig):
    from dataclasses import replace

    preview = await sharing.preview(rig.owner, "root")
    sharing.config = replace(sharing.config, public_origin="")
    with pytest.raises(OctopError) as err:
        await sharing.create(rig.owner, "root", preview["preview_digest"])
    assert err.value.code == "SHARE_ORIGIN_REQUIRED" and err.value.status == 503
    assert sharing.list(rig.owner)["shares"] == []
    assert (await sharing.preview(rig.owner, "root"))["preview_digest"] == preview["preview_digest"]


@pytest.mark.asyncio
async def test_http_real_jwt_exact_anonymous_get_and_openapi(sharing, rig):
    secret = rig.repos.secret_repo.get_or_create("jwt", lambda: b"x" * 48)

    def user(uid):
        row = rig.repos.user_repo.get(uid)
        return SimpleNamespace(
            id=uid, username=row.username, role="admin", disabled=False, is_admin=True
        )

    server = SimpleNamespace(
        _started=True,
        services=SimpleNamespace(
            repos=rig.repos, config=sharing.config, secret_repo=rig.repos.secret_repo
        ),
        user_manager=SimpleNamespace(get_by_id=user),
        app_runtime=SimpleNamespace(agent_registry=rig.manager, history_archive=sharing.archive),
    )
    app = FastAPI()
    _install_exception_handlers(app)
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_server] = lambda: server
    install(app, server)

    def auth(uid):
        return {
            "Authorization": "Bearer "
            + sign_token(secret, sub=uid, uname="user", role="admin", ttl_seconds=86400)
        }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        base = "/api/agents/parent/threads/root"
        assert (await client.get(base + "/share-preview")).status_code == 401
        preview = (await client.get(base + "/share-preview", headers=auth(rig.owner))).json()
        created = await client.post(
            base + "/shares",
            headers=auth(rig.owner),
            json={"preview_digest": preview["preview_digest"]},
        )
        assert created.status_code == 201, created.text
        row = created.json()
        token = row["public_path"].split("/")[-1]
        public = "/api/public/thread-shares/" + token
        response = await client.get(public)
        assert response.status_code == 200, response.text
        assert set(response.json()["messages"][0]) == {"id", "role", "content"}
        for hidden in ("PRIVATE_", "internal-resource", "source_thread", "parent", "root"):
            assert hidden not in response.text
        for header in ("cache-control", "x-robots-tag", "referrer-policy"):
            assert header in response.headers
        for method in ("post", "put", "delete", "head", "options"):
            assert (await getattr(client, method)(public)).status_code == 401
        assert (await client.get("/api/public/thread-shares")).status_code == 401
        assert (await client.get(public + "/other")).status_code == 401
        assert (await client.get("/api/public/thread-shares/bad")).status_code == 404
        foreign = auth(rig.outsider)
        assert (
            await client.get(base + "/shares?as_user=" + str(rig.owner), headers=foreign)
        ).status_code == 404
        assert (
            await client.delete("/api/thread-shares/" + row["share_id"], headers=foreign)
        ).status_code == 404
        assert (await client.get("/api/thread-shares", headers=foreign)).json()["shares"] == []
        closed = await client.delete(
            "/api/thread-shares/" + row["share_id"], headers=auth(rig.owner)
        )
        assert closed.status_code == 204
        missing = await client.get(public)
        assert missing.status_code == 404 and missing.headers["cache-control"] == "no-store"
    schema = app.openapi()
    assert schema["paths"]["/api/public/thread-shares/{token}"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["$ref"].endswith("PublicSnapshot")


@pytest.mark.asyncio
async def test_native_registration_policy_runtime_authority_and_audit(sharing, rig):
    names = {"octop_thread_share_" + suffix for suffix in ("preview", "create", "list", "revoke")}
    tools = {
        tool.name: tool
        for tool in build_native_management_tools(rig.manager, rig.repos, "parent", sharing=sharing)
    }
    assert names <= set(tools) & set(NATIVE_TOOL_NAMES) & HOST_TOOLS_ALLOWED

    async def call(name, **kwargs):
        return json.loads(await tools["octop_thread_share_" + name].ainvoke(kwargs))

    token = var_child_runnable_config.set(
        {"configurable": {"user": rig.owner, "thread_id": "root", "conversation_mode": "craft"}}
    )
    try:
        preview = await call("preview")
        created = await call("create", preview_digest=preview["preview_digest"])
        assert created["public_url"].startswith("https://share.example.com/share/")
        assert (await call("list"))["shares"][0]["share_id"] == created["share_id"]
        for mode in ("ask", "plan"):
            mode_token = var_child_runnable_config.set(
                {"configurable": {"user": rig.owner, "thread_id": "root", "work_mode": mode}}
            )
            try:
                assert "messages" in await call("preview")
                assert "shares" in await call("list")
                assert (await call("create", preview_digest=preview["preview_digest"]))["error"][
                    "code"
                ] == "FORBIDDEN"
                assert (await call("revoke", share_id=created["share_id"]))["error"][
                    "code"
                ] == "FORBIDDEN"
            finally:
                var_child_runnable_config.reset(mode_token)
        rig.manager.get_config = lambda _: {"tools_disabled": ["octop_thread_share_create"]}
        assert "error" in await call("create", preview_digest=preview["preview_digest"])
        rig.manager.get_config = lambda _: {"tools_disabled": []}
        assert (await call("revoke", share_id=created["share_id"]))["status"] == "revoked"
        with rig.repos.db.connect() as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM audit_log WHERE action='octop_thread_share_create'"
                ).fetchone()[0]
                >= 2
            )
    finally:
        var_child_runnable_config.reset(token)


def test_projector_config_and_token_log_redaction(tmp_path, monkeypatch):
    assert public_text("<think>SECRET</think>Answer") == "Answer"
    assert (
        public_text(
            "![secret](/api/agents/private/media) [local](file:///secret) [web](https://example.com)"
        )
        == "local [web](https://example.com)"
    )
    assert (
        public_text(
            [{"type": "image_url", "image_url": "PRIVATE"}, {"type": "text", "text": "Text"}]
        )
        == "Text"
    )
    assert public_text("[image offloaded: sha=abc path=PRIVATE size=4B mime=image/png]") == ""
    for bad in (
        "http://example.com",
        "https://localhost",
        "https://127.0.0.1",
        "https://user:pass@example.com",
        "https://example.com/path",
        "https://example.com/?secret",
        "https://example.com/#x",
    ):
        with pytest.raises(ValueError):
            validate_public_origin(bad)
    monkeypatch.setenv("OCTOP_PUBLIC_ORIGIN", "https://example.com/")
    assert load_config(tmp_path / "config.json").public_origin == "https://example.com"
    assert "thread-shares" in SIDEBAR_NAV_KEYS
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "x",
        1,
        "GET %s",
        ("/api/public/thread-shares/" + "x" * 43,),
        None,
    )
    QuerySecretFilter().filter(record)
    assert "x" * 43 not in record.getMessage() and "[REDACTED]" in record.getMessage()
