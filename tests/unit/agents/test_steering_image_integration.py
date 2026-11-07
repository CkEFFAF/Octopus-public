"""Uploaded images reach the resumed model while SQLite keeps lightweight references."""

from __future__ import annotations

import asyncio
import base64
import io
import json
from types import SimpleNamespace
from typing import Any

import pytest
from deepagents.backends.local_shell import LocalShellBackend
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from octop_gateway.models import FileContent, ImageContent, InboundMessage, TextContent
from octop_harness.backends.workspace import BackendWorkspace
from octop_harness.protocols.langgraph import LangGraphProtocol
from octop_harness.steering import LiveSteeringMiddleware, StreamSteering
from PIL import Image
from pydantic import Field
from tests.unit.agents.test_collaboration_resources import rig as resource_rig

from octop.api.common.attachments import save_attachment
from octop.infra.agents.middleware.workspace_image import WorkspaceImageMaterializeMiddleware
from octop.infra.errors import OctopError
from octop.infra.gateway.process.processor import GlobalProcessor

rig = resource_rig


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [None, "replace", "revoke", "replace_during_prepare"])
async def test_uploaded_image_and_file_survive_live_insertion_and_sqlite_reload(
    rig: Any, tmp_path: Any, mutation: str | None
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = BackendWorkspace(
        LocalShellBackend(root_dir=str(root), virtual_mode=False), str(root)
    )
    rig.workspaces["parent"] = workspace
    rig.manager.octop_config = SimpleNamespace(max_upload_bytes=10 * 1024**2)
    stream = io.BytesIO()
    Image.new("RGB", (16, 12), (20, 80, 160)).save(stream, format="PNG")
    png = stream.getvalue()
    image = await save_attachment(
        workspace, owner_id=rig.owner, filename="中文补充.png", media_type="image/png", data=png
    )
    document = await save_attachment(
        workspace,
        owner_id=rig.owner,
        filename="中文要求.txt",
        media_type="text/plain",
        data="要求：保留中文。".encode(),
    )
    attachments = []
    for stored, name, kind, media in [
        (image, "中文补充.png", "image", "image/png"),
        (document, "中文要求.txt", "file", "text/plain"),
    ]:
        resource = await rig.resources.register(
            rig.owner, "parent", stored.data_path, thread="root", media_type=media
        )
        attachments.append(
            {
                "filename": name,
                "workspace_path": stored.data_path,
                "kind": kind,
                "media_type": media,
                "resource_id": resource["resource_id"],
                "version": resource["version"],
            }
        )
    inbound = InboundMessage(
        channel_id="dashboard",
        channel_type="dashboard",
        content=[
            TextContent(text="结合图片和要求继续"),
            ImageContent(
                local_path=image.data_path, filename="中文补充.png", mime_type="image/png"
            ),
            FileContent(
                local_path=document.data_path, filename="中文要求.txt", mime_type="text/plain"
            ),
        ],
        metadata={"octop_inbound_attachments": attachments},
    )
    processor = object.__new__(GlobalProcessor)
    processor._agent_manager = rig.manager
    processor._user_repo = rig.repos.user_repo
    if mutation == "replace_during_prepare":
        original_prepare = processor._resource_input

        async def replace_before_registration(*args: Any, **kwargs: Any) -> Any:
            await workspace.aupload_bytes(image.data_path, b"changed content")
            return await original_prepare(*args, **kwargs)

        processor._resource_input = replace_before_registration
        with pytest.raises(ValueError, match="RESOURCE_VERSION_CHANGED"):
            await processor.prepare_steering_message(inbound, "parent", rig.owner, "root")
        return
    prepared = await processor.prepare_steering_message(inbound, "parent", rig.owner, "root")
    assert any(
        part.get("type") == "image_url" and part["image_url"]["url"].startswith("workspace://")
        for part in prepared.content
    )
    assert base64.b64encode(png).decode() not in json.dumps(
        prepared.model_dump(), ensure_ascii=False
    )

    class CaptureModel(FakeMessagesListChatModel):
        seen: list[Any] = Field(default_factory=list)

        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
            return self

        def _generate(self, messages: Any, *args: Any, **kwargs: Any) -> Any:
            self.seen.append(messages)
            return super()._generate(messages, *args, **kwargs)

    started, release = asyncio.Event(), asyncio.Event()
    effects = []

    @tool
    async def once() -> str:
        """Finish one previously admitted operation."""
        effects.append("one")
        started.set()
        await release.wait()
        return "done"

    control = StreamSteering()
    config = {
        "configurable": {
            "thread_id": "root",
            "user": rig.owner,
            "harness_steering_run_id": control.run_id,
        }
    }
    model = CaptureModel(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "once", "args": {}, "id": "once"}]),
            AIMessage(content="已结合图片继续"),
        ]
    )
    database = str(tmp_path / "checkpoints.db")
    async with AsyncSqliteSaver.from_conn_string(database) as saver:
        graph = create_agent(
            model,
            tools=[once],
            middleware=[
                LiveSteeringMiddleware({"root": control}),
                WorkspaceImageMaterializeMiddleware(
                    workspace=workspace, resource_service=rig.resources, agent_id="parent"
                ),
            ],
            checkpointer=saver,
        )

        async def consume() -> list[dict[str, Any]]:
            return [
                chunk
                async for chunk in LangGraphProtocol(graph=graph).stream(
                    [HumanMessage(content="original")], config
                )
            ]

        task = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), 10)
        assert control.request("image-insert", inbound.text, message=prepared) == "accepted"
        if mutation == "replace":
            await workspace.aupload_bytes(image.data_path, b"changed content")
        elif mutation == "revoke":
            original = rig.resources.repo.get(
                "collaboration_resources", rig.owner, attachments[0]["resource_id"]
            )
            rig.resources.repo.save(
                "collaboration_resources",
                rig.owner,
                original["resource_id"],
                "root",
                {**original, "revoked": True},
                "resource.revoked",
                event_id="revoke-qa",
                resource_id=original["resource_id"],
                previous=original,
            )
        release.set()
        if mutation:
            with pytest.raises(OctopError):
                await asyncio.wait_for(task, 10)
            assert not any(
                message.id == "steer:image-insert" for request in model.seen for message in request
            )
            return
        chunks = await asyncio.wait_for(task, 10)
        for request in model.seen:
            for message in request:
                if message.id == "steer:image-insert":
                    urls = [
                        part["image_url"]["url"]
                        for part in message.content
                        if part.get("type") == "image_url"
                    ]
                    assert len(urls) == 1 and urls[0].startswith("data:image/png;base64,")
                    assert base64.b64decode(urls[0].split(",", 1)[1]) == png
        assert any(
            message.id == "steer:image-insert" for request in model.seen for message in request
        )
        async for state in graph.aget_state_history(config):
            assert base64.b64encode(png).decode() not in json.dumps(
                [m.model_dump() for m in state.values.get("messages", [])], ensure_ascii=False
            )
        assert effects == ["one"]
        assert sum(chunk.get("type") == "steering_applied" for chunk in chunks) == 1
    async with AsyncSqliteSaver.from_conn_string(database) as saver:
        stored = await saver.aget(config)
        humans = [m for m in stored["channel_values"]["messages"] if m.id == "steer:image-insert"]
        assert len(humans) == 1
        assert (
            humans[0].additional_kwargs["octop_inbound_attachments"]
            == prepared.additional_kwargs["octop_inbound_attachments"]
        )
        assert any(
            part.get("type") == "image_url" and part["image_url"]["url"].startswith("workspace://")
            for part in humans[0].content
        )
