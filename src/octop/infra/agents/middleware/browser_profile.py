"""Force browser tool calls onto the current user's isolated profile."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.config import get_config
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from octop.infra.execution.service import ExecutionService
from octop.infra.utils.browser_media import parse_octop_user_id, user_browser_profile

logger = logging.getLogger(__name__)

_BROWSER_TOOL = "browser_use"
_MISSING_USER = (
    "browser_use blocked: the current turn has no Octop user id, "
    "so a browser profile cannot be isolated."
)


def _bind_browser_profile(request: ToolCallRequest) -> ToolCallRequest | ToolMessage:
    tool_call = request.tool_call
    if str(tool_call.get("name") or "") != _BROWSER_TOOL:
        return request

    configurable = dict(get_config().get("configurable") or {})
    user_id = parse_octop_user_id(configurable.get("user"))
    if user_id is None:
        logger.warning("browser_use blocked: configurable.user is missing or invalid")
        return ToolMessage(
            content=_MISSING_USER,
            tool_call_id=str(tool_call.get("id") or ""),
            status="error",
        )

    raw_args = tool_call.get("args")
    args = dict(raw_args) if isinstance(raw_args, dict) else {}
    args["profile"] = user_browser_profile(user_id)
    return request.override(tool_call={**tool_call, "args": args})


class BrowserProfileMiddleware(AgentMiddleware[Any, Any]):
    """Prevent model-selected profiles from crossing Octop user boundaries."""

    def __init__(self, executions: ExecutionService | None = None, agent_id: str = "") -> None:
        self.executions = executions
        self.agent_id = agent_id

    def _remote(self, request: ToolCallRequest) -> bool:
        if request.tool_call.get("name") != _BROWSER_TOOL:
            return False
        cfg = get_config().get("configurable") or {}
        return self.executions is not None or bool(
            cfg.get("octop_execution_context") or cfg.get("octop_device_target")
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        bound = _bind_browser_profile(request)
        if isinstance(bound, ToolMessage):
            return bound
        if self._remote(bound):
            return ToolMessage(
                content="device browser requires asynchronous execution",
                tool_call_id=str(request.tool_call.get("id") or ""),
                status="error",
            )
        return handler(bound)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        bound = _bind_browser_profile(request)
        if isinstance(bound, ToolMessage):
            return bound
        if self._remote(bound):
            from octop.infra.execution.browser import browser_tool

            try:
                cfg = get_config().get("configurable") or {}
                context = cfg.get("octop_execution_context") or {}
                if self.executions is None or not context.get("context_id"):
                    raise ValueError(
                        "selected device has no execution context; browser cannot fall back to control center"
                    )
                result = await browser_tool(
                    self.executions,
                    int(cfg["user"]),
                    context["context_id"],
                    self.agent_id,
                    bound.tool_call["args"],
                )
                return ToolMessage(
                    content=result, tool_call_id=str(bound.tool_call.get("id") or "")
                )
            except Exception as exc:
                return ToolMessage(
                    content=str(exc)[:1000],
                    tool_call_id=str(bound.tool_call.get("id") or ""),
                    status="error",
                )
        return await handler(bound)


__all__ = ["BrowserProfileMiddleware"]
