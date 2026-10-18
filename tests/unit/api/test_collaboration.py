"""Typed collaboration HTTP uses real stored history and owner checks."""

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from tests.unit.agents.test_collaboration_resources import call
from tests.unit.agents.test_collaboration_resources import rig as rig

from octop.api.app import _install_exception_handlers
from octop.api.deps import current_user, get_server
from octop.api.routers.chat.collaboration import router
from octop.infra.history.projection import message_inputs


@pytest.mark.asyncio
async def test_http_real_public_child_roles_content_and_cross_account_denial(rig):
    peer = call(rig)
    rig.collaboration.accept(peer)
    rig.collaboration.bind(peer, "child-thread", {})
    rig.repos.thread_message_repo.append_if_ready(
        "child-thread",
        message_inputs(
            [
                HumanMessage(content="Read the paper", id="question"),
                AIMessage(
                    content="Public answer",
                    id="answer",
                    additional_kwargs={"reasoning_content": "PRIVATE_REASONING"},
                ),
                ToolMessage(content="PRIVATE_TOOL_BODY", tool_call_id="tool", id="tool"),
            ]
        ),
    )
    resource = await rig.resources.register(rig.owner, "parent", "inbound/paper.txt", thread="root")
    app = FastAPI()
    _install_exception_handlers(app)
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_server] = lambda: SimpleNamespace(
        app_runtime=SimpleNamespace(agent_registry=rig.manager)
    )
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=rig.owner)
    base = "/api/agents/parent/threads/root"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(base + "/collaboration/inv-1")
        assert response.status_code == 200, response.text
        body = response.json()
        assert [(m["role"], m["content"]) for m in body["messages"]] == [
            ("user", "Read the paper"),
            ("assistant", "Public answer"),
        ]
        assert "PRIVATE_" not in response.text
        listing = await client.get(base + "/collaboration?limit=1")
        assert listing.status_code == 200
        cursor = listing.json()["next_cursor"]
        later = (await client.get(base + f"/collaboration?after={cursor}")).json()
        assert all(event["seq"] > cursor for event in later["events"])
        content_url = base + "/resources/" + resource["resource_id"] + "/content"
        content = await client.get(content_url)
        assert content.status_code == 200 and content.content == b"A paper with source text."
        assert (
            "snapshot_locator" not in (await client.get(content_url.removesuffix("/content"))).text
        )
        app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=rig.outsider)
        for path in (base + "/collaboration", base + "/collaboration/inv-1", content_url):
            denied = await client.get(path)
            assert denied.status_code == 403
            assert "paper.txt" not in denied.text and "PRIVATE_" not in denied.text
    assert "/api/agents/{agent_id}/threads/{thread_id}/collaboration" in app.openapi()["paths"]


@pytest.mark.asyncio
async def test_uploaded_resource_is_validated_through_prepare_and_actual_processor_input(
    rig, monkeypatch
):
    from unittest.mock import AsyncMock, MagicMock

    from octop_gateway.models import InboundMessage

    from octop.api.routers.chat.models import ChatTurnBody
    from octop.api.routers.chat.turn import prepare_dashboard_turn
    from octop.api.routers.uploads import router as upload_router
    from octop.infra.devices.service import DeviceService
    from octop.infra.gateway.process.processor import GlobalProcessor
    from octop.infra.gateway.slash.dispatcher import SlashDispatcher
    from octop.infra.gateway.threads import ThreadRegistry

    workspace = rig.workspaces["parent"]

    async def exists(path):
        return path in workspace.files

    async def upload(path, data):
        workspace.files[path] = data

    workspace.aexists = exists
    workspace.aupload_bytes = upload
    monkeypatch.setattr(
        "octop.api.routers.uploads.require_running_workspace", AsyncMock(return_value=workspace)
    )
    monkeypatch.setattr(
        "octop.api.routers.chat.turn.validate_chat_mcp_servers", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        "octop.api.routers.chat.turn.validate_chat_skills", AsyncMock(return_value=[])
    )
    rig.manager.get_row = rig.repos.agent_repo.get
    rig.manager.get_config = lambda aid: {}
    registry = ThreadRegistry(
        session_repo=rig.repos.session_repo, thread_repo=rig.repos.thread_repo
    )
    devices = DeviceService(rig.repos, local_state_dir=rig.manager.paths.root / "native")
    server = SimpleNamespace(
        app_runtime=SimpleNamespace(
            agent_registry=rig.manager,
            gateway=SimpleNamespace(thread_registry=registry),
            devices=devices,
        ),
        services=SimpleNamespace(config=SimpleNamespace(max_upload_bytes=8 * 1024 * 1024)),
    )
    user = SimpleNamespace(id=rig.owner, is_admin=True, locale="en")
    app = FastAPI()
    app.include_router(upload_router, prefix="/api")
    app.dependency_overrides[get_server] = lambda: server
    app.dependency_overrides[current_user] = lambda: user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/agents/parent/upload",
                files={"file": ("report.txt", b"Authenticated uploaded paper", "text/plain")},
            )
        assert response.status_code == 200, response.text
        resource = response.json()
        prepared = await prepare_dashboard_turn(
            server,
            agent_id="parent",
            user=user,
            turn=ChatTurnBody(
                thread_id="root",
                skills=[],
                mcp_servers=[],
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Delegate the reading"},
                            {
                                "type": "file",
                                "workspace_path": resource["workspace_path"],
                                "filename": "report.txt",
                                "media_type": "text/plain",
                                "resource_id": "forged-client-id",
                            },
                        ],
                    }
                ],
            ),
        )
        assert prepared.inbound_attachments[0]["resource_id"] == resource["resource_id"]
        processor = GlobalProcessor(
            agent_manager=rig.manager,
            thread_registry=registry,
            audit_repo=rig.repos.audit_repo,
            agent_repo=rig.repos.agent_repo,
            user_repo=rig.repos.user_repo,
            connector_repo=rig.repos.connector_repo,
            dispatcher=SlashDispatcher(),
        )
        monkeypatch.setattr(
            "octop.infra.gateway.process.processor.media_backend_for_agent", lambda *args: None
        )
        processor._resolve_harness_model = lambda *a, **k: None
        processor._resolve_reasoning_overrides = lambda *a, **k: {}
        processor._resolve_turn_mcp_servers = AsyncMock(return_value=[])
        processor._attach_turn_knowledge_config = MagicMock()
        processor._stamp_turn_conversation_mode = lambda request, **kwargs: request
        msg = InboundMessage(
            channel_id="octop-dashboard", channel_type="dashboard", content=prepared.inbound_content
        )
        request = await processor._build_dashboard_request(
            msg,
            agent_id="parent",
            user_id=rig.owner,
            session_key=prepared.session_key,
            thread_id=prepared.thread_id,
            meta={
                "mcp_servers": [],
                "octop_inbound_attachments": [{"resource_id": "forged-metadata-id"}],
            },
        )
        raw = request["messages"][0]
        content = raw.content if hasattr(raw, "content") else raw["content"]
        encoded = json.dumps(content, ensure_ascii=False)
        assert resource["resource_id"] in encoded and resource["version"] in encoded
        assert "read_attachment" in encoded and "resource_ids" in encoded
        assert "forged-" not in encoded
        kwargs = (
            raw.additional_kwargs
            if hasattr(raw, "additional_kwargs")
            else raw.get("additional_kwargs", {})
        )
        assert kwargs["octop_inbound_attachments"][0]["resource_id"] == resource["resource_id"]
        invocation = rig.collaboration.accept(call(rig, resources=(resource["resource_id"],)))
        assert invocation["resource_ids"] == [resource["resource_id"]]
    finally:
        await devices.shutdown()


@pytest.mark.asyncio
async def test_large_binary_upload_resource_downloads_but_parser_has_separate_limit(
    rig, monkeypatch
):
    import hashlib
    from unittest.mock import AsyncMock

    from octop.api.routers.uploads import router as upload_router
    from octop.config import OctopConfig

    workspace = rig.workspaces["parent"]

    async def exists(path):
        return path in workspace.files

    async def upload(path, data):
        workspace.files[path] = data

    workspace.aexists = exists
    workspace.aupload_bytes = upload
    rig.manager.octop_config = OctopConfig()
    monkeypatch.setattr(
        "octop.api.routers.uploads.require_running_workspace", AsyncMock(return_value=workspace)
    )
    server = SimpleNamespace(
        app_runtime=SimpleNamespace(agent_registry=rig.manager),
        services=SimpleNamespace(config=rig.manager.octop_config),
    )
    app = FastAPI()
    _install_exception_handlers(app)
    app.include_router(upload_router, prefix="/api")
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_server] = lambda: server
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=rig.owner)
    data = b"\x00" + b"b" * (9 * 1024 * 1024 - 1)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/agents/parent/upload",
            files={"file": ("data.bin", data, "application/octet-stream")},
        )
        assert response.status_code == 200, response.text
        uploaded = response.json()
        resource = await rig.resources.register(
            rig.owner, "parent", uploaded["workspace_path"], thread="root"
        )
        assert (
            resource["size"] == len(data)
            and resource["version"] == hashlib.sha256(data).hexdigest()
        )
        content = await client.get(
            "/api/agents/parent/threads/root/resources/" + resource["resource_id"] + "/content"
        )
        assert (
            content.status_code == 200
            and hashlib.sha256(content.content).hexdigest() == resource["version"]
        )
        read = await rig.resources.read(
            rig.owner, "parent", "root", resource_id=resource["resource_id"]
        )
        assert (
            read["status"] == "error"
            and read["code"] == "DOCUMENT_LIMIT"
            and read["retryable"] is False
        )
