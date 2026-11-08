"""Send execution files through the same verified snapshots as published artifacts."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.config import get_config
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command
from octop_harness.middleware.conversation_mode import ConversationModeMiddleware

from octop.i18n import tr
from octop.infra.documents.resources import ResourceService
from octop.infra.errors import OctopError


class FileDeliveryMiddleware(AgentMiddleware[Any, Any]):
    def __init__(self, resources: ResourceService, agent_id: str) -> None:
        self.resources = resources
        self.agent_id = agent_id
        self.mode_guard = ConversationModeMiddleware()

    async def _deliver(self, request: ToolCallRequest) -> ToolMessage | None:
        call = request.tool_call
        if call.get("name") != "send_file_to_user":
            return None
        cfg = get_config().get("configurable") or {}
        context = cfg.get("octop_execution_context")
        if not isinstance(context, dict) or not context.get("context_id"):
            return None
        args = call.get("args") or {}
        path = args.get("file_path")
        # The virtual expert store has its own backend and existing send tool.
        if isinstance(path, str) and path.replace("\\", "/").startswith("/.agent/"):
            return None

        async def publish(_: ToolCallRequest) -> ToolMessage | Command[Any]:
            return await self._publish(call, cfg, context, path)

        return cast(ToolMessage, await self.mode_guard.awrap_tool_call(request, publish))

    async def _publish(
        self, call: Mapping[str, Any], cfg: dict[str, Any], context: dict[str, Any], path: Any
    ) -> ToolMessage:
        try:
            if not isinstance(path, str) or not path.strip():
                raise ValueError("RESOURCE_SOURCE_INVALID")
            resource = await self.resources.publish(
                int(cfg.get("user") or 0),
                self.agent_id,
                str(cfg.get("thread_id") or ""),
                path,
                str(context["context_id"]),
                run_id=str(cfg.get("octop_task_run_id") or ""),
            )
            content = {
                "status": "published",
                **self.resources.public(resource, self.agent_id, str(cfg.get("thread_id") or "")),
            }
            status = "success"
        except Exception as exc:
            code = exc.code.value if isinstance(exc, OctopError) else "RESOURCE_UNAVAILABLE"
            content = {
                "status": "failed",
                "is_error": True,
                "error": {"code": code},
                "message": tr("resources.unavailable", str(cfg.get("language") or "en")),
            }
            status = "error"
        return ToolMessage(
            content=json.dumps(content, ensure_ascii=False),
            tool_call_id=str(call.get("id") or ""),
            name="send_file_to_user",
            status=status,
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        result = asyncio.run(self._deliver(request))
        return result if result is not None else handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        result = await self._deliver(request)
        return result if result is not None else await handler(request)
