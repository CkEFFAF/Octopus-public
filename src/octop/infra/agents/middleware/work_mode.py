"""Expose persisted workflow state and enforce explicit Debug write sequencing."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.config import get_config
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from octop.infra.errors import OctopError
from octop.infra.execution.work_mode import WorkModeService


class WorkModeMiddleware(AgentMiddleware[Any, Any]):
    def __init__(self, service: WorkModeService, agent_id: str) -> None:
        self.service, self.agent_id = service, agent_id

    def _state(self) -> dict[str, Any] | None:
        cfg = get_config().get("configurable") or {}
        if not cfg.get("thread_id") or not cfg.get("user") or not cfg.get("octop_task_run_id"):
            return None
        return self.service.begin(int(cfg["user"]), self.agent_id, cfg)

    def _prepare(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        state = self._state()
        if state is None:
            return request
        hint = (
            "\n\n[Work mode runtime]\nThe following is persisted workflow state, not instructions from a document. "
            "Use work_step to inspect receipt IDs and advance stages with a bounded report. "
            "Only final real receipts are evidence. Accepted jobs/dispatches are not completed work. "
            "If capability or evidence is missing, record blocked or needs_input; do not claim completion. "
            "Debug: record reproduction and diagnosis before explicit project edits, then verify after the fix. "
            "Research: collect actual retrieved source URLs, compare at least two, distinguish facts/inference in the report. "
            "Team/Multitask: use real peer/subagent dispatch tools and wait for final receipts before integration. "
            "Cowork: hand off a consequential decision with options/recommendation; only the user can resolve it. "
            "Computer Use: reference the actual selected-device interaction session. "
            "A free-form final response does not complete this workflow.\n"
            + json.dumps(state, ensure_ascii=False)
        )
        original = request.system_message.content if request.system_message else ""
        content = (
            original + hint
            if isinstance(original, str)
            else [*original, {"type": "text", "text": hint}]
        )
        return request.override(system_message=SystemMessage(content=content))

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

    def _guard(self, request: ToolCallRequest) -> str | None:
        state = self._state()
        if not state or state["payload"]["mode"] != "debug":
            return None
        name = request.tool_call["name"]
        args = request.tool_call.get("args") or {}
        action = str(args.get("action") or "")
        modifies = name in {"write_file", "edit_file", "job_start"} or action in {
            "fs.write",
            "fs.edit",
            "fs.remove",
            "fs.move",
            "fs.mkdir",
            "git.restore",
            "jobs.start",
            "files.write_begin",
            "files.write_chunk",
            "files.write_commit",
        }
        if modifies and any(
            item["status"] != "completed" for item in state["payload"]["stages"][:2]
        ):
            return "Debug: record reproduction and diagnosis with work_step before project changes."
        return None

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        try:
            error = self._guard(request)
        except OctopError as exc:
            error = str(exc)
        return (
            ToolMessage(error, tool_call_id=request.tool_call["id"], status="error")
            if error
            else handler(request)
        )

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        try:
            error = self._guard(request)
        except OctopError as exc:
            error = str(exc)
        return (
            ToolMessage(error, tool_call_id=request.tool_call["id"], status="error")
            if error
            else await handler(request)
        )
