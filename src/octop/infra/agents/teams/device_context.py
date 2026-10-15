"""Preserve request-scoped device consent across inbox dispatch and follow-up."""

from __future__ import annotations

import asyncio
import logging
import time
from contextvars import ContextVar
from copy import deepcopy
from typing import Any

from langgraph.config import get_config

from octop.infra.agents.conversation_mode import stamp_conversation_mode
from octop.infra.errors import ErrorCode, OctopError

_KEY = "octop_runtime_context"
_context: ContextVar[dict[str, Any] | None] = ContextVar("octop_peer_runtime", default=None)


def restore_peer_context(request: dict[str, Any]) -> dict[str, Any]:
    context = _context.get()
    if context is None:
        return request
    owner = context["owner"]
    if str(request.get("user")) != str(owner):
        raise OctopError(ErrorCode.FORBIDDEN, "peer request owner changed")
    inherited = context["configurable"]
    target = inherited.get("octop_device_target")
    if target:
        devices = context["devices"]
        if devices is None:
            raise OctopError(ErrorCode.FORBIDDEN, "device service unavailable")
        device = devices.owned(owner, target["device_id"])
        if device.grant_version != target["grant_version"]:
            raise OctopError(ErrorCode.FORBIDDEN, "selected device permissions changed")
    cfg = dict(request.get("configurable") or {})
    cfg.update(deepcopy(inherited))
    request["configurable"] = cfg
    mode = inherited.get("conversation_mode")
    existing = request.get("conversation_mode")
    # A child may be more restrictive than its caller, never less restrictive.
    if existing == "ask" or mode == "ask":
        stamp_conversation_mode(request, "ask")
    elif existing == "plan" or mode == "plan":
        stamp_conversation_mode(request, "plan")
    elif mode == "craft":
        stamp_conversation_mode(request, "craft")
    for key in ("skills", "mcp_servers"):
        if inherited.get(key) == []:
            request[key] = []
    return request


def _capture(owner: int) -> dict[str, Any]:
    try:
        cfg = get_config().get("configurable") or {}
    except RuntimeError:
        cfg = {}
    current = _context.get()
    if not cfg and current is not None:
        cfg = current["configurable"]
    if cfg.get("user") is not None and str(cfg["user"]) != str(owner):
        raise OctopError(ErrorCode.FORBIDDEN, "peer dispatch owner changed")
    snapshot = {
        key: deepcopy(cfg[key])
        for key in (
            "octop_device_target",
            "octop_execution_context",
            "octop_task_run_id",
            "conversation_mode",
            "work_mode",
        )
        if key in cfg
    }
    for key in ("skills", "mcp_servers"):
        if cfg.get(key) == []:
            snapshot[key] = []
    return {"owner": owner, "configurable": snapshot}


def _payload(request: Any) -> dict[str, Any]:
    if isinstance(request, dict):
        return dict(request)
    return {
        key: value
        for key, value in vars(request).items()
        if value is not None and not key.startswith("_")
    }


def _restore_request(request: Any) -> Any:
    payload = restore_peer_context(_payload(request))
    if isinstance(request, dict):
        return payload
    for key in ("configurable", "conversation_mode", "skills", "mcp_servers", "mcp_use_default"):
        if key in payload:
            setattr(request, key, payload[key])
    if payload.get("conversation_mode") in {"ask", "plan"}:
        request.mcp_use_default = False
    return request


class PeerTaskTracker:
    def __init__(self, devices: Any) -> None:
        self.devices = devices
        self.jobs: dict[tuple[int, str, str], tuple[Any, str]] = {}
        self.cancelled_runs: set[tuple[int, str]] = set()

    def _receipt(
        self,
        snapshot: dict[str, Any],
        job_id: str,
        agent_id: str,
        thread_id: str | None,
        target: str,
        status: str,
    ) -> None:
        if self.devices is None or getattr(self.devices, "repos", None) is None or not thread_id:
            return
        from octop.infra.execution.events import RunInspectionService

        cfg = snapshot.get("configurable") or {}
        if not cfg.get("octop_task_run_id"):
            return
        receipt = {
            "event_id": f"dispatch:{job_id}",
            "owner_user_id": snapshot["owner"],
            "thread_id": thread_id,
            "run_id": cfg["octop_task_run_id"],
            "context_id": (cfg.get("octop_execution_context") or {}).get("context_id"),
            "created_at": time.time(),
            "kind": "dispatch",
            "status": status,
            "payload": {"job_id": job_id, "target_agent_id": target, "name": "ask_agent"},
        }
        try:
            RunInspectionService(self.devices.repos).tool_receipt(agent_id, receipt)
        except Exception:
            logging.getLogger(__name__).warning(
                "Failed to retain peer dispatch receipt %s", job_id, exc_info=True
            )

    def context(self, metadata: dict[str, Any], owner: Any) -> dict[str, Any] | None:
        saved = metadata.get(_KEY)
        if not isinstance(saved, dict):
            return None
        if str(saved.get("owner")) != str(owner):
            raise RuntimeError("inbox owner changed")
        return {**deepcopy(saved), "devices": self.devices}

    async def wait_for_task_run(self, owner: int, run_id: str) -> None:
        while True:
            jobs = [value for key, value in self.jobs.items() if key[:2] == (owner, run_id)]
            if any(status in {"failed", "cancelled"} for _, status in jobs):
                raise OctopError(ErrorCode.TASK_BOARD_INVALID, "task peer execution failed")
            if all(status == "done" for _, status in jobs):
                self.jobs = {
                    key: value for key, value in self.jobs.items() if key[:2] != (owner, run_id)
                }
                return
            await asyncio.sleep(0.1)

    async def cancel_task_run(self, owner: int, run_id: str) -> None:
        self.cancelled_runs.add((owner, run_id))
        for key, (inbox, status) in list(self.jobs.items()):
            if key[:2] != (owner, run_id) or status in {"done", "failed", "cancelled"}:
                continue
            inbox.cancel(key[2])
            task = getattr(inbox, "_tasks", {}).get(key[2])
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self.jobs[key] = (inbox, "cancelled")

    def install(self, team: Any) -> None:
        if getattr(team, "_octop_peer_tasks", None) is not None:
            return
        inbox = getattr(team, "inbox", None)
        submit = getattr(team, "submit_peer", None)
        if submit is None or inbox is None:
            return
        team._octop_peer_tasks = self

        def child_finished(msg: Any, status: str) -> None:
            self._receipt(
                msg.metadata.get(_KEY) or {},
                msg.id,
                msg.source_agent_id,
                msg.source_thread_id,
                msg.target_agent_id,
                "completed" if status == "done" else status,
            )

        inbox.bind_result_observer(child_finished)

        def submit_peer(**kwargs: Any) -> Any:
            owner = int(kwargs["user_id"])
            snapshot = _capture(owner)
            run_id = snapshot["configurable"].get("octop_task_run_id")
            if (owner, run_id) in self.cancelled_runs:
                raise OctopError(ErrorCode.FORBIDDEN, "task already cancelled")
            metadata = {**(kwargs.get("metadata") or {}), _KEY: snapshot}
            result = submit(**{**kwargs, "metadata": metadata})
            if run_id and result.job_id:
                self.jobs[(owner, run_id, result.job_id)] = (inbox, "pending")
                self._receipt(
                    snapshot,
                    result.job_id,
                    kwargs["from_agent_id"],
                    kwargs.get("source_thread_id"),
                    kwargs["to_agent_id"],
                    "accepted",
                )
            return result

        team.submit_peer = submit_peer
        original_invoke = team._invoke_peer

        async def invoke_peer(**kwargs: Any) -> Any:
            msg = inbox.get(kwargs.get("job_id")) if kwargs.get("job_id") else None
            saved = (
                self.context(msg.metadata, msg.user_id)
                if msg is not None
                else {**_capture(int(kwargs["user_id"])), "devices": self.devices}
            )
            token = _context.set(saved)
            try:
                return await original_invoke(**kwargs)
            except OctopError as exc:
                # Harness inbox catches RuntimeError, not application domain errors.
                raise RuntimeError(str(exc)) from exc
            finally:
                _context.reset(token)

        team._invoke_peer = invoke_peer
        # Build/enrich hooks can swallow preparation errors, so validate at invocation too.
        for name in ("_build_peer_request", "_enrich_request", "_call_agent"):
            original = getattr(team, name, None)
            if original is None:
                continue

            def wrap(method: Any, method_name: str) -> Any:
                async def call(*args: Any, **kwargs: Any) -> Any:
                    if method_name == "_call_agent" and _context.get() is not None:
                        args = (*args[:-1], _restore_request(args[-1]))
                    result = await method(*args, **kwargs)
                    if method_name != "_call_agent" and _context.get() is not None:
                        result = _restore_request(result)
                    return result

                return call

            setattr(team, name, wrap(original, name))
        inbox._call_agent = team._call_agent

        synthesize = inbox._synthesize_reply

        async def synthesize_reply(msg: Any, result_text: Any, error_text: Any) -> Any:
            token = _context.set(self.context(msg.metadata, msg.user_id))
            try:
                return await synthesize(msg, result_text, error_text)
            except OctopError as exc:
                raise RuntimeError(str(exc)) from exc
            finally:
                _context.reset(token)

        inbox._synthesize_reply = synthesize_reply
        finish = inbox._finish

        async def finish_job(msg: Any, **kwargs: Any) -> Any:
            saved = msg.metadata.get(_KEY) or {}
            key = (int(msg.user_id), saved.get("configurable", {}).get("octop_task_run_id"), msg.id)
            try:
                result = await finish(msg, **kwargs)
            except BaseException:
                if key in self.jobs:
                    self.jobs[key] = (inbox, "failed")
                raise
            if key in self.jobs:
                self.jobs[key] = (inbox, kwargs["status"])
            return result

        inbox._finish = finish_job
