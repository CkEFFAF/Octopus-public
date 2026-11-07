"""Ephemeral workspace-image rematerialization for model calls (plan B).

Checkpoint / history keep path-only ``image_url`` refs (``workspace://…``).
This middleware expands them to ``data:`` URIs on the model request only so
base64 never lands in LangGraph state or the dashboard history payload.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langgraph.config import get_config

from octop.infra.documents.resources import ResourceService, denied
from octop.infra.gateway.media.attachment_hints import (
    expand_workspace_image_ref,
    expand_workspace_image_ref_sync,
    is_workspace_image_ref,
    workspace_path_from_image_ref,
)
from octop.infra.utils.browser_media import parse_octop_user_id

if TYPE_CHECKING:
    from octop_harness.backends.workspace import BackendWorkspace


class WorkspaceImageMaterializeMiddleware(AgentMiddleware[Any, Any]):
    """Inline ``workspace://`` vision refs just before the provider call."""

    def __init__(
        self,
        *,
        workspace: BackendWorkspace,
        resource_service: ResourceService | None = None,
        agent_id: str | None = None,
    ) -> None:
        self._workspace = workspace
        self._resources = resource_service
        self._agent_id = agent_id

    async def _image_source(self, msg: Any, block: dict[str, Any]) -> bytes | None:
        """Recheck admitted resources and read their immutable version at use time."""
        attachments = getattr(msg, "additional_kwargs", {}).get("octop_inbound_attachments")
        if not self._resources or not isinstance(attachments, list):
            return None
        path = workspace_path_from_image_ref(block)
        attachment = next(
            (
                item
                for item in attachments
                if isinstance(item, dict) and item.get("workspace_path") == path
            ),
            None,
        )
        # Legacy messages and tool screenshots have no versioned resource receipt.
        if attachment is None or not attachment.get("resource_id"):
            return None
        config = get_config().get("configurable") or {}
        owner = parse_octop_user_id(config.get("user"))
        thread = str(config.get("thread_id") or "")
        if owner is None or not thread or not self._agent_id:
            raise denied()
        resource_id = str(attachment["resource_id"])
        resource = self._resources.authorize(owner, resource_id, self._agent_id, thread)
        if not attachment.get("version") or resource["version"] != attachment["version"]:
            raise denied()
        data = await self._resources.bytes(owner, resource)
        # A resource can be revoked while its snapshot is being read.
        current = self._resources.authorize(owner, resource_id, self._agent_id, thread)
        if current["version"] != resource["version"]:
            raise denied()
        return data

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        messages = self._expand_messages_sync(request.messages)
        return handler(request.override(messages=messages))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        messages = await self._expand_messages(request.messages)
        return await handler(request.override(messages=messages))

    def _expand_messages_sync(self, messages: Sequence[Any]) -> list[Any]:
        out: list[Any] = []
        for msg in messages:
            content = getattr(msg, "content", None)
            if not isinstance(content, list) or not any(
                is_workspace_image_ref(block) for block in content if isinstance(block, dict)
            ):
                out.append(msg)
                continue
            new_blocks: list[Any] = [
                (
                    expand_workspace_image_ref_sync(
                        block,
                        workspace=self._workspace,
                        source_bytes=asyncio.run(self._image_source(msg, block)),
                    )
                    if isinstance(block, dict) and is_workspace_image_ref(block)
                    else block
                )
                for block in content
            ]
            out.append(msg.model_copy(update={"content": new_blocks}))
        return out

    async def _expand_messages(self, messages: Sequence[Any]) -> list[Any]:
        out: list[Any] = []
        for msg in messages:
            content = getattr(msg, "content", None)
            if not isinstance(content, list) or not any(
                is_workspace_image_ref(block) for block in content if isinstance(block, dict)
            ):
                out.append(msg)
                continue
            new_blocks: list[Any] = []
            for block in content:
                if isinstance(block, dict) and is_workspace_image_ref(block):
                    new_blocks.append(
                        await expand_workspace_image_ref(
                            block,
                            workspace=self._workspace,
                            source_bytes=await self._image_source(msg, block),
                        )
                    )
                else:
                    new_blocks.append(block)
            out.append(msg.model_copy(update={"content": new_blocks}))
        return out


__all__ = ["WorkspaceImageMaterializeMiddleware"]
