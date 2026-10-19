"""Limit delegated outcome reporting to the current authenticated child invocation."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from octop.infra.agents.teams.collaboration import runtime_config
from octop.infra.agents.teams.task_results import TaskResultService, build_task_result_tools
from octop.infra.errors import OctopError

logger = logging.getLogger(__name__)


def _tool_name(tool: Any) -> str:
    if isinstance(tool, str):
        return tool
    if isinstance(tool, dict):
        function = tool.get("function")
        return str(function.get("name") if isinstance(function, dict) else tool.get("name", ""))
    return str(getattr(tool, "name", ""))


class TaskResultAvailabilityMiddleware(AgentMiddleware[Any, Any]):
    def __init__(self, manager: Any, agent_id: str) -> None:
        self.service = TaskResultService(manager)
        self.agent_id = agent_id
        self.tools = build_task_result_tools(manager, agent_id)

    def _prepare(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        if not any(_tool_name(tool) == "report_task_result" for tool in request.tools):
            return request
        cfg = runtime_config()
        eligible = False
        if cfg.get("octop_invocation_id"):
            try:
                invocation = self.service.bound_invocation(self.agent_id, cfg)
                eligible = invocation["transport_status"] == "running"
            except OctopError:
                eligible = False
            except Exception as exc:
                logger.error("Task result availability lookup failed (%s)", type(exc).__name__)
        if eligible:
            return request
        return request.override(
            tools=[tool for tool in request.tools if _tool_name(tool) != "report_task_result"]
        )

    def wrap_model_call(
        self, request: ModelRequest[Any], handler: Callable[[ModelRequest[Any]], ModelResponse[Any]]
    ) -> ModelResponse[Any]:
        return handler(self._prepare(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        return await handler(await asyncio.to_thread(self._prepare, request))
