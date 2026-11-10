"""Apply a portable model context recipe without changing archived messages."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.config import get_config
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from octop.infra.workflow_graphs.state import ContextRecipe


def graph_config() -> dict[str, Any]:
    try:
        cfg = get_config().get("configurable") or {}
        value = cfg.get("octop_graph_context")
        return value if isinstance(value, dict) else {}
    except RuntimeError:
        return {}


def project_messages(messages: list[AnyMessage], recipe: ContextRecipe) -> list[AnyMessage]:
    start = 0
    if recipe.history != "full":
        humans = [i for i, message in enumerate(messages) if isinstance(message, HumanMessage)]
        if humans:
            turns = recipe.recent_turns if recipe.history == "recent" else 1
            start = humans[max(0, len(humans) - turns)]
        calls = {
            call["id"]: i
            for i, message in enumerate(messages)
            if isinstance(message, AIMessage)
            for call in message.tool_calls
            if call.get("id")
        }
        cursor = len(messages) - 1
        while cursor >= start:
            message = messages[cursor]
            if isinstance(message, ToolMessage):
                start = min(start, calls.get(message.tool_call_id, 0))
            cursor -= 1
    result = [m for i, m in enumerate(messages) if i >= start or isinstance(m, SystemMessage)]
    if recipe.inject:
        # Data has user priority and never becomes a persistent or system instruction.
        result = [*result, HumanMessage(content="[Workflow context data]\n" + recipe.inject)]
    return result


class WorkflowContextMiddleware(AgentMiddleware[Any, Any]):
    def __init__(self, service: Any, agent_id: str) -> None:
        self.service = service
        self.agent_id = agent_id

    def _check(self) -> dict[str, Any]:
        cfg = graph_config()
        if cfg:
            self.service.check_worker(cfg, self.agent_id, time.time())
        return cfg

    def _prepare(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        cfg = self._check()
        if not cfg:
            return request
        recipe = ContextRecipe.model_validate(cfg["recipe"])
        return request.override(messages=project_messages(list(request.messages), recipe))

    def wrap_model_call(
        self, request: ModelRequest[Any], handler: Callable[[ModelRequest[Any]], ModelResponse[Any]]
    ) -> ModelResponse[Any]:
        return handler(self._prepare(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        return await handler(self._prepare(request))

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        self._check()
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        self._check()
        return await handler(request)
