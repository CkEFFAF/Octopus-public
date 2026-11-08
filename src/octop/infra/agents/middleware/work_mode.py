"""Expose persisted workflow state and enforce explicit Debug write sequencing."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage
from langgraph.config import get_config
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from octop.infra.agents.middleware.request_context import (
    append_system_hint,
    capture_context,
    replay_context,
)
from octop.infra.errors import OctopError
from octop.infra.execution.foreground_policy import foreground_wait_error
from octop.infra.execution.work_mode import WorkModeService


class WorkModeMiddleware(AgentMiddleware[Any, Any]):
    _SNAPSHOT_KEY = "_octop_work_mode_context"

    def __init__(self, service: WorkModeService, agent_id: str) -> None:
        self.service, self.agent_id = service, agent_id

    def _state(self) -> dict[str, Any] | None:
        cfg = get_config().get("configurable") or {}
        if not cfg.get("thread_id") or not cfg.get("user") or not cfg.get("octop_task_run_id"):
            return None
        return self.service.begin(int(cfg["user"]), self.agent_id, cfg)

    def _context(self) -> str:
        state = self._state()
        return (
            "\n\n[Work mode runtime snapshot]\n" + json.dumps(state, ensure_ascii=False)
            if state
            else ""
        )

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return capture_context(state, self._SNAPSHOT_KEY, self._context)

    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.before_model, state, runtime)

    def _prepare(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        cfg = get_config().get("configurable") or {}
        if cfg.get("octop_wakeup_event_only"):
            request = request.override(tools=[])
        hint = (
            "\n\n[Work mode runtime]\nRuntime snapshots accompany individual user messages. "
            "They describe persisted state when that message arrived. "
            "Use work_step to inspect receipt IDs and advance stages with a bounded report. "
            "Only final real receipts are evidence. Accepted jobs/dispatches are not completed work. "
            "Foreground execute is for work up to 60 seconds. Never sleep or poll to hold the conversation. "
            "For a future check, schedule one self-check and finish your answer. "
            "For long work, use job_start with a short task title in the user's language, then report acceptance and finish your answer. "
            "Job completion feedback wakes this original thread once; do not repeatedly poll or create duplicate reminders. "
            "If capability or evidence is missing, record blocked or needs_input; do not claim completion. "
            "Debug: record reproduction and diagnosis before explicit project edits, then verify after the fix. "
            "Research: collect actual retrieved source URLs, compare at least two, distinguish facts/inference in the report. "
            "Team/Multitask: use real peer/subagent dispatch tools and wait for final receipts before integration. "
            "Cowork: hand off a consequential decision with options/recommendation; only the user can resolve it. "
            "Computer Use: reference the actual selected-device interaction session. "
            "A free-form final response does not complete this workflow.\n"
        )
        return request.override(
            system_message=append_system_hint(request, hint),
            messages=replay_context(request, self._SNAPSHOT_KEY),
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
        return await handler(self._prepare(request))

    def _guard(self, request: ToolCallRequest) -> str | None:
        try:
            cfg = get_config().get("configurable") or {}
        except RuntimeError:
            cfg = {}
        if cfg.get("octop_wakeup_event_only"):
            from octop.i18n import tr

            return tr("execution.eventOnlyToolsDisabled", str(cfg.get("language") or "en"))
        error = foreground_wait_error(
            request.tool_call["name"],
            request.tool_call.get("args") or {},
            str(cfg.get("language") or "en"),
        )
        if error:
            return error
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
