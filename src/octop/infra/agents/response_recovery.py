"""Resume an identified model checkpoint without submitting another human turn."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Any
from uuid import uuid4

from anyio import CancelScope
from langchain_core.messages import AIMessage, ToolMessage
from octop_harness.protocols.langgraph import LangGraphProtocol
from octop_harness.protocols.think_splitter import ThinkSplitter
from octop_harness.request import ChatRequest

from octop.i18n import tr
from octop.i18n.domains.stream import classify_model_error
from octop.infra.agents.security.hitl_session import hitl_thread_scope
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.model_diagnostics import safe_diagnostics

logger = logging.getLogger(__name__)
RECOVERY_INVOCATION_ID = "octop_response_attempt"
_PENDING_RECEIPT_STATUSES = frozenset({"accepted", "running"})


def checkpoint_id(state: Any) -> str:
    value = (getattr(state, "config", None) or {}).get("configurable", {}).get(
        "checkpoint_id"
    ) or ""
    return value if isinstance(value, str) else ""


def model_boundary(state: Any) -> bool:
    return tuple(getattr(state, "next", ())) == ("model",) and all(
        getattr(task, "name", "") == "model" and not getattr(task, "interrupts", ())
        for task in getattr(state, "tasks", ())
    )


def _failed_tool_call_id(state: Any) -> str | None:
    tasks: tuple[Any, ...] = getattr(state, "tasks", ())
    if tuple(getattr(state, "next", ())) != ("tools",) or len(tasks) != 1:
        return None
    task = tasks[0]
    if task.name != "tools" or not task.error or task.interrupts or task.result is not None:
        return None
    messages = (state.values or {}).get("messages") or []
    if not messages or not isinstance(messages[-1], AIMessage):
        return None
    calls = messages[-1].tool_calls
    return calls[0].get("id") if len(calls) == 1 else None


def recovery_request(request: dict[str, Any]) -> dict[str, Any]:
    """Persist routing identities, never prompts, attachment bytes or tool secrets."""
    result = {
        key: copy.deepcopy(request[key])
        for key in (
            "agent_id",
            "thread_id",
            "user",
            "source",
            "model",
            "mcp_servers",
            "mcp_use_default",
            "skills",
            "conversation_mode",
            "knowledge_base_ids",
        )
        if key in request
    }
    original = request.get("configurable") or {}
    config = {
        key: copy.deepcopy(original[key])
        for key in (
            "session_key",
            "work_mode",
            "conversation_mode",
            "octop_reasoning_overrides",
            "octop_model_route",
            "knowledge_base_ids",
            "locale",
        )
        if key in original
    }
    context = original.get("octop_execution_context")
    if isinstance(context, dict) and context.get("context_id"):
        config["octop_execution_context"] = {"context_id": context["context_id"]}
    else:
        config["octop_recovery_without_target"] = True
    result["configurable"] = config
    result["messages"] = []
    return result


class ResumeModelProtocol(LangGraphProtocol):
    """Use the pinned Harness projection and controls with LangGraph None resume."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._resumed = False

    async def stream(
        self, messages: list[Any], config: dict[str, Any], **kwargs: Any
    ) -> AsyncGenerator[dict[str, Any], None]:
        if self._resumed:
            # Harness may admit steering just after the final model hook.
            # Its follow-up must start from the latest state, not the original
            # recovery checkpoint, which would branch away from that answer.
            followup = {**config, "configurable": dict(config.get("configurable") or {})}
            followup["configurable"].pop("checkpoint_id", None)
            followup["configurable"].pop("checkpoint_ns", None)
            async for event in super().stream(messages, followup, **kwargs):
                yield event
            return
        self._resumed = True
        splitter = ThinkSplitter()
        invocation_id = (config.get("metadata") or {}).get("harness_invocation_id")
        async for part in self._graph.astream(
            None,
            config=config,
            stream_mode=["values", "updates", "messages", "custom"],
            version="v2",
            **kwargs,
        ):
            for event in self._project_chunk(part, splitter, invocation_id):
                yield event
        for event in self._drain_splitter(splitter):
            yield event


class ResponseRecovery:
    def __init__(self, manager: Any) -> None:
        self.manager = manager
        self.repos = manager._repos

    def authorize(self, owner: int, agent: str, thread: str) -> None:
        actor = self.repos.user_repo.get(owner)
        if actor is None or actor.disabled:
            raise OctopError(ErrorCode.FORBIDDEN, "Account unavailable")
        row = self.repos.thread_repo.get(thread)
        if row is None or row.user_id != owner or row.agent_id != agent:
            raise OctopError(ErrorCode.NOT_FOUND, "Response not found")

    async def record(
        self, agent: str, request: dict[str, Any], exc: Exception | None = None
    ) -> dict[str, Any] | None:
        if not str(request.get("source") or "").startswith("dashboard"):
            return None
        thread = str(request.get("thread_id") or "")
        owner = int(request.get("user") or 0)
        if not thread or not owner:
            return None
        harness = self.manager.get_agent(agent)
        state = await harness.graph.aget_state({"configurable": {"thread_id": thread}})
        invocation_id = (request.get("metadata") or {}).get(RECOVERY_INVOCATION_ID)
        if (
            invocation_id
            and (getattr(state, "metadata", None) or {}).get(RECOVERY_INVOCATION_ID)
            != invocation_id
        ):
            # An invocation can fail before it commits any input. The latest
            # checkpoint then belongs to a different turn.
            return None
        current = checkpoint_id(state)
        if not current:
            return None
        failed_call = _failed_tool_call_id(state) if exc is not None else None
        boundary = state if exc is not None and (model_boundary(state) or failed_call) else None
        if exc is None and not getattr(state, "next", ()):
            final = list((getattr(state, "values", None) or {}).get("messages") or [])
            # Regenerate only the final model call. All completed tools and
            # human messages must be exactly the already-committed prefix.
            if (
                final
                and getattr(final[-1], "type", "") == "ai"
                and not getattr(final[-1], "tool_calls", ())
            ):
                async for prior in harness.graph.aget_state_history(
                    {"configurable": {"thread_id": thread}}, limit=32
                ):
                    prefix = list((getattr(prior, "values", None) or {}).get("messages") or [])
                    if model_boundary(prior) and [getattr(m, "id", None) for m in prefix] == [
                        getattr(m, "id", None) for m in final[:-1]
                    ]:
                        boundary = prior
                        break
        if boundary is None:
            return None
        response_id = (
            "chat-response:"
            + hashlib.sha256(f"{owner}:{agent}:{thread}:{current}".encode()).hexdigest()[:40]
        )
        diagnostic = (
            safe_diagnostics(
                exc,
                code=classify_model_error(exc) or "MODEL_CALL_FAILED",
                stage="chat",
                job_id=thread,
            )
            if exc
            else {}
        )
        payload = {
            "checkpoint_id": current,
            "resume_checkpoint_id": checkpoint_id(boundary),
            "request": recovery_request(request),
            "action": "retry" if exc else "regenerate",
            **({"failed_tool_call_id": failed_call} if failed_call else {}),
            "retry_at": time.time() + float(diagnostic.get("retry_after_seconds") or 0),
        }
        await asyncio.to_thread(
            self.repos.run_event_repo.save,
            event_id=response_id,
            owner=owner,
            agent_id=agent,
            thread_id=thread,
            run_id=response_id,
            context_id=None,
            kind="chat_response",
            status="failed" if exc else "completed",
            payload=payload,
        )
        return {
            "response_id": response_id,
            "retry_at": payload["retry_at"],
            "action": payload["action"],
        }

    async def latest(self, owner: int, agent: str, thread: str) -> dict[str, Any]:
        await asyncio.to_thread(self.authorize, owner, agent, thread)
        rows = await asyncio.to_thread(
            self.repos.run_event_repo.list, owner, agent, thread, kind="chat_response", limit=1
        )
        if not rows:
            raise OctopError(ErrorCode.RESPONSE_RECOVERY_CONFLICT, "RESPONSE_RECOVERY_UNAVAILABLE")
        record = rows[0]
        state = await self.manager.get_agent(agent).graph.aget_state(
            {"configurable": {"thread_id": thread}}
        )
        if checkpoint_id(state) != record["payload"]["checkpoint_id"]:
            raise OctopError(ErrorCode.RESPONSE_RECOVERY_CONFLICT, "RESPONSE_RECOVERY_STALE")
        return {
            "response_id": record["event_id"],
            "retry_at": record["payload"]["retry_at"],
            "action": record["payload"]["action"],
        }

    async def stream(
        self,
        owner: int,
        agent: str,
        thread: str,
        response_id: str,
        command_id: str,
        model: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        await asyncio.to_thread(self.authorize, owner, agent, thread)
        receipts = self.repos.run_event_repo
        event_id = f"chat-retry:{owner}:{command_id}"
        lock = self.manager._thread_execution_lock(agent, thread)
        prior = await asyncio.to_thread(receipts.get, owner, event_id)
        if prior is not None:
            if (
                prior["kind"] != "chat_retry"
                or prior["thread_id"] != thread
                or prior["agent_id"] != agent
                or prior["payload"].get("response_id") != response_id
                or prior["payload"].get("model") != model
            ):
                raise OctopError(
                    ErrorCode.RESPONSE_RECOVERY_CONFLICT, "RESPONSE_RECOVERY_COMMAND_CONFLICT"
                )
            status = prior["status"]
            if status in _PENDING_RECEIPT_STATUSES and not lock.locked():
                async with lock:
                    # An idle thread cannot still own this execution. Keep
                    # the command's identity so a replay never runs it again.
                    updated = await asyncio.to_thread(
                        receipts.compare_payload,
                        owner,
                        event_id,
                        prior["payload"],
                        prior["payload"],
                        "unknown",
                        expected_status=status,
                    )
                    current = (
                        None if updated else await asyncio.to_thread(receipts.get, owner, event_id)
                    )
                    status = current["status"] if current else "unknown"
            if status in _PENDING_RECEIPT_STATUSES:
                status = "running"
            yield {"type": "recovery_ack", "status": status, "response_id": response_id}
            return
        if lock.locked():
            raise OctopError(ErrorCode.RESPONSE_RECOVERY_CONFLICT, "RESPONSE_RECOVERY_BUSY")
        async with lock, self.manager._track_invocation(agent):
            await asyncio.to_thread(self.authorize, owner, agent, thread)
            record = await asyncio.to_thread(receipts.get, owner, response_id)
            if (
                record is None
                or record["kind"] != "chat_response"
                or record["thread_id"] != thread
                or record["agent_id"] != agent
            ):
                raise OctopError(ErrorCode.NOT_FOUND, "Response not found")
            payload = record["payload"]
            harness = self.manager.get_agent(agent)
            current = await harness.graph.aget_state({"configurable": {"thread_id": thread}})
            if checkpoint_id(current) != payload["checkpoint_id"]:
                raise OctopError(ErrorCode.RESPONSE_RECOVERY_CONFLICT, "RESPONSE_RECOVERY_STALE")
            if time.time() < payload["retry_at"]:
                raise OctopError(ErrorCode.RESPONSE_RECOVERY_CONFLICT, "RESPONSE_RECOVERY_COOLDOWN")
            checkpoint = await harness.graph.aget_state(
                {
                    "configurable": {
                        "thread_id": thread,
                        "checkpoint_id": payload["resume_checkpoint_id"],
                    }
                }
            )
            failed_call = payload.get("failed_tool_call_id")
            if failed_call and _failed_tool_call_id(checkpoint) != failed_call:
                raise OctopError(
                    ErrorCode.RESPONSE_RECOVERY_CONFLICT, "RESPONSE_RECOVERY_UNAVAILABLE"
                )
            if not failed_call and not model_boundary(checkpoint):
                raise OctopError(
                    ErrorCode.RESPONSE_RECOVERY_CONFLICT, "RESPONSE_RECOVERY_UNAVAILABLE"
                )
            original_request = copy.deepcopy(payload["request"])
            if model and model != original_request.get("model"):
                # Provider-specific thinking fields from the original model
                # are not portable to a replacement model.
                original_request.setdefault("configurable", {}).pop(
                    "octop_reasoning_overrides", None
                )
            if model:
                original_request["model"] = model
                route = (original_request.get("configurable") or {}).get("octop_model_route")
                if isinstance(route, dict) and route.get("model") != model:
                    route.update(model=model, source="manual", reason="manual", available=True)
            actor = await asyncio.to_thread(self.repos.user_repo.get, owner)
            values = original_request.setdefault("configurable", {})
            values["user_is_admin"] = bool(actor and actor.role == "admin")
            if "knowledge_base_ids" in values:
                from octop.infra.knowledge.hint import catalog_for_selected_bases

                bases = await asyncio.to_thread(
                    self.repos.knowledge_repo.list_all
                    if values["user_is_admin"]
                    else lambda: self.repos.knowledge_repo.list_visible(owner)
                )
                selected = values["knowledge_base_ids"]
                if set(selected) - {row.id for row in bases}:
                    raise OctopError(ErrorCode.FORBIDDEN, "Knowledge access changed")
                values["knowledge_base_catalog"] = catalog_for_selected_bases(bases, selected)
            saved_context = values.get("octop_execution_context")
            if not isinstance(saved_context, dict) or not saved_context.get("context_id"):
                values["octop_recovery_without_target"] = True
            request = await asyncio.to_thread(
                self.manager._prepare_stream_request, agent, original_request
            )
            # A continuation has no new user messages. HarnessAgent._prepare_call
            # normalizes a new turn and rejects its empty message list.
            config = ChatRequest.coerce(request).to_runnable_config()
            config["metadata"] = {
                **config.get("metadata", {}),
                "harness_invocation_id": uuid4().hex,
            }
            config.setdefault("configurable", {}).update(
                {
                    "checkpoint_id": payload["resume_checkpoint_id"],
                    "checkpoint_ns": (getattr(checkpoint, "config", None) or {})
                    .get("configurable", {})
                    .get("checkpoint_ns", ""),
                }
            )
            reservation = {"response_id": response_id, "model": model}
            with CancelScope(shield=True):
                await asyncio.to_thread(
                    receipts.save,
                    event_id=event_id,
                    owner=owner,
                    agent_id=agent,
                    thread_id=thread,
                    run_id=event_id,
                    context_id=None,
                    kind="chat_retry",
                    status="accepted",
                    payload=reservation,
                    replace=False,
                )
                claimed = await asyncio.to_thread(
                    receipts.compare_payload,
                    owner,
                    event_id,
                    reservation,
                    {**reservation, "claimed": True},
                    "running",
                    expected_status="accepted",
                )
            if not claimed:
                yield {"type": "recovery_ack", "status": "running", "response_id": response_id}
                return
            baseline = {
                str(getattr(m, "id", ""))
                for m in (getattr(checkpoint, "values", None) or {}).get("messages", [])
            }
            status = "unknown"
            model_refs = getattr(self.manager, "_active_model_refs", None)
            route = (request.get("configurable") or {}).get("octop_model_route")
            try:
                yield {"type": "recovery_ack", "status": "accepted", "response_id": response_id}
                if isinstance(model_refs, dict) and request.get("model"):
                    model_refs[(agent, thread)] = request["model"]
                if failed_call:
                    # Account for the failed call before resuming. Invoking the
                    # tools checkpoint itself could repeat external side effects.
                    updated = await harness.graph.aupdate_state(
                        config,
                        {
                            "messages": [
                                ToolMessage(
                                    tr(
                                        "execution.interruptedTool",
                                        str(values.get("locale") or "en"),
                                    ),
                                    tool_call_id=failed_call,
                                    status="error",
                                )
                            ]
                        },
                        as_node="tools",
                        task_id=checkpoint.tasks[0].id,
                    )
                    config["configurable"]["checkpoint_id"] = updated["configurable"][
                        "checkpoint_id"
                    ]
                if isinstance(route, dict):
                    yield {**route, "type": "model_route"}
                with hitl_thread_scope(thread):
                    async with harness._invocation():
                        async with aclosing(
                            self._resume_chunks(harness, config, thread, baseline)
                        ) as chunks:
                            async for chunk in chunks:
                                if chunk.get("type") == "hitl_required":
                                    status = "paused"
                                if (
                                    chunk.get("type") == "run_phase"
                                    and chunk.get("phase") == "cancelled"
                                ):
                                    status = "cancelled"
                                yield chunk
                if status not in {"cancelled", "paused"}:
                    status = "completed"
                try:
                    await self.record(agent, request)
                except Exception:
                    logger.exception("Could not record response recovery thread=%s", thread)
            except Exception as exc:
                status = "failed"
                try:
                    recovery = await self.record(agent, request, exc)
                    if recovery:
                        exc.octop_response_recovery = recovery  # type: ignore[attr-defined]
                except Exception:
                    logger.exception("Could not record response recovery thread=%s", thread)
                raise
            finally:
                if isinstance(model_refs, dict):
                    model_refs.pop((agent, thread), None)
                with CancelScope(shield=True):
                    await asyncio.to_thread(
                        receipts.save,
                        event_id=event_id,
                        owner=owner,
                        agent_id=agent,
                        thread_id=thread,
                        run_id=event_id,
                        context_id=None,
                        kind="chat_retry",
                        status=status,
                        payload={"response_id": response_id, "model": model, "claimed": True},
                    )

    @staticmethod
    async def _resume_chunks(
        harness: Any, config: dict[str, Any], thread: str, baseline: set[str]
    ) -> AsyncGenerator[dict[str, Any], None]:
        # Keep the original message/tool prefix out of the new archive attempt.
        async with aclosing(
            harness._stream_with_steering(
                ResumeModelProtocol(graph=harness.graph), [], config, thread
            )
        ) as chunks:
            async for chunk in chunks:
                if chunk.get("type") in {"state_snapshot", "state_update"} and isinstance(
                    chunk.get("data"), dict
                ):
                    data = dict(chunk["data"])
                    if isinstance(data.get("messages"), list):
                        data["messages"] = [
                            m for m in data["messages"] if str(getattr(m, "id", "")) not in baseline
                        ]
                    chunk = {**chunk, "data": data}
                yield chunk
