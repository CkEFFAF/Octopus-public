"""Record recovery attempts without duplicating the original human message."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from octop.i18n.domains.stream import classify_model_error, format_stream_error
from octop.infra.agents.response_recovery import ResponseRecovery
from octop.infra.errors import OctopError
from octop.infra.gateway.hitl.coordinator import HitlStreamContext
from octop.infra.gateway.hitl.format import normalize_hitl_request
from octop.infra.gateway.media.tool_media import (
    enrich_tool_result_for_dashboard,
    enrich_tool_result_with_backend,
    iter_dashboard_attachment_frames,
)
from octop.infra.gateway.process.agent_resolve import harness_workspace_for_agent
from octop.infra.gateway.process.stream_project import enrich_tool_stream_chunk
from octop.infra.gateway.process.usage_record import UsageTracker
from octop.infra.history.recorder import flush_tracker
from octop.infra.utils.model_diagnostics import safe_diagnostics


async def iter_response_recovery(
    *,
    manager: Any,
    processor: Any,
    owner: int,
    agent: str,
    thread: str,
    response_id: str,
    command_id: str,
    locale: str,
    model: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    tracker = None
    completed = False
    paused = False
    cancelled = False
    usage = UsageTracker()
    trajectory = processor._agent_trajectory_enabled(agent)
    workspace = harness_workspace_for_agent(manager, agent)
    saw_tool_call = False
    emitted_media_ids: set[str] = set()
    emitted_attachment_keys: set[str] = set()
    try:
        async for chunk in ResponseRecovery(manager).stream(
            owner, agent, thread, response_id, command_id, model
        ):
            if chunk.get("type") == "recovery_ack":
                if chunk.get("status") == "accepted":
                    tracker = await processor._begin_history(agent, thread, {})
                yield chunk
                continue
            usage.observe(chunk)
            processor._observe_trajectory(
                agent_id=agent, thread_id=thread, chunk=chunk, enabled=trajectory
            )
            if chunk.get("type") == "hitl_required" and isinstance(chunk.get("request"), dict):
                request = normalize_hitl_request(chunk["request"])
                row = manager._repos.thread_repo.get(thread)
                pending = processor._hitl.register_from_request(
                    request,
                    ctx=HitlStreamContext(
                        thread_id=thread,
                        agent_id=agent,
                        user_id=owner,
                        session_key=row.session_key,
                        channel_type="dashboard",
                    ),
                )
                request["pending_id"] = pending.pending_id
                chunk = {**chunk, "request": request, "pending_id": pending.pending_id}
                paused = True
            if tracker is not None:
                tracker.observe(chunk)
                await flush_tracker(tracker)
            if chunk.get("type") == "tool_call_chunk":
                saw_tool_call = True
            if chunk.get("type") == "tool_result":
                if workspace is not None:
                    chunk = await enrich_tool_result_with_backend(
                        chunk, agent_id=agent, workspace=workspace
                    )
                    async for attachment in iter_dashboard_attachment_frames(
                        chunk,
                        agent_id=agent,
                        workspace=workspace,
                        saw_tool_call=saw_tool_call,
                        emitted_media_ids=emitted_media_ids,
                        emitted_attachment_keys=emitted_attachment_keys,
                    ):
                        yield attachment
                else:
                    chunk = enrich_tool_result_for_dashboard(chunk, agent_id=agent)
            chunk = enrich_tool_stream_chunk(
                chunk, locale, agent_manager=manager, agent_id=agent, user_id=owner
            )
            if chunk.get("type") == "run_phase" and chunk.get("phase") == "cancelled":
                cancelled = True
                yield chunk
                return
            yield chunk
        completed = not paused
    except Exception as exc:
        code = (
            exc.code.value
            if isinstance(exc, OctopError)
            else classify_model_error(exc) or "octop:stream_errors.model_call_failed"
        )
        chunk = {
            "type": "error",
            "message": exc.localized_message(locale)
            if isinstance(exc, OctopError)
            else format_stream_error(exc, locale),
            "error_code": code,
            "diagnostic": safe_diagnostics(exc, code=code, stage="chat_recovery", job_id=thread),
        }
        if tracker is not None:
            tracker.observe(chunk)
            await processor._record_stream_error(user_id=owner, agent_id=agent, exc=exc)
        yield chunk
    finally:
        if tracker is not None:
            processor._finish_trajectory(thread_id=thread, usage=usage.usage, enabled=trajectory)
            if paused:
                tracker.paused = True
                await processor._finish_history(tracker, completed=False)
            elif completed:
                processor._touch_thread_after_turn(thread, None)
                processor._record_turn_usage(
                    agent_id=agent, user_id=owner, thread_id=thread, usage=usage.usage
                )
                await processor._complete_resumed_history(thread, tracker, completed=True)
            else:
                await processor._persist_incomplete_turn(thread, tracker, title_source=None)
            if processor._gateway is not None:
                await processor._gateway.emit_thread_changed(
                    owner_user_id=owner,
                    agent_id=agent,
                    thread_id=thread,
                    reason="attention"
                    if paused
                    else "cancelled"
                    if cancelled
                    else "completed"
                    if completed
                    else "failed",
                )
    yield {"type": "done"}
