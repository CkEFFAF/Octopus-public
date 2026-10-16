"""Inspect related execution receipts without retaining file, screen or log bodies."""

from __future__ import annotations

from typing import Any

from octop.infra.db.repos.execution import ExecutionContext, ExecutionContextRepo
from octop.infra.db.repos.run_events import RunEventRepo
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError

# Polling streams have independent state and offsets; never append an event per frame.
STREAM_ACTIONS = frozenset(
    {
        "terminal.poll",
        "terminal.input",
        "terminal.resize",
        "desktop.capture",
        "desktop.input",
        "jobs.logs",
        "jobs.status",
        "jobs.list",
        "acp.poll",
        "acp.write",
        "browser.capture",
        "browser.state",
        "browser.observe",
        "browser.action",
        "fs.upload.chunk",
        "fs.upload.status",
        "fs.download.chunk",
    }
)


COMMAND_PREVIEW_CAP = 512
OUTPUT_PREVIEW_CAP = 2048
RECEIPT_SCALAR_KEYS = frozenset(
    {
        "job_id",
        "status",
        "returncode",
        "session_id",
        "sha256",
        "size",
        "recovery_id",
        "recovery_copy",
        "restored",
        "backup_path",
        "cancel_requested",
        "cancel_incomplete",
    }
)


def command_preview_from_params(params: dict[str, Any]) -> str | None:
    """Bounded argv/command preview for run_event payloads (never fabricate)."""
    argv = params.get("argv")
    if isinstance(argv, list) and argv and all(isinstance(part, str) for part in argv):
        try:
            import subprocess

            text = subprocess.list2cmdline(list(argv))
        except Exception:
            text = " ".join(argv)
        text = text.strip()
        return text[:COMMAND_PREVIEW_CAP] if text else None
    for key in ("command", "cmd"):
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:COMMAND_PREVIEW_CAP]
    return None


def bound_receipt_fields(result: dict[str, Any]) -> dict[str, Any]:
    """Whitelist receipt scalars + bounded stdout/stderr previews."""
    receipt: dict[str, Any] = {
        key: value[:4096] if isinstance(value, str) else value
        for key, value in result.items()
        if key in RECEIPT_SCALAR_KEYS and isinstance(value, (str, int, float, bool, type(None)))
    }
    truncated = bool(result.get("truncated") is True)
    for source, preview_key in (
        ("stdout", "stdout_preview"),
        ("stderr", "stderr_preview"),
    ):
        value = result.get(source)
        if not isinstance(value, str) or not value:
            continue
        if len(value) > OUTPUT_PREVIEW_CAP:
            receipt[preview_key] = value[:OUTPUT_PREVIEW_CAP]
            truncated = True
        else:
            receipt[preview_key] = value
    if truncated:
        receipt["output_truncated"] = True
    return receipt


class RunInspectionService:
    def __init__(self, repos: RepoBundle) -> None:
        self.repos = repos
        self.events = RunEventRepo(repos.db)

    def interaction_observation(
        self, context: ExecutionContext, action: str, params: dict[str, Any]
    ) -> None:
        """Update one session/action receipt; never retain screen or input contents."""
        self.events.save(
            event_id=f"interaction:{context.context_id}:{action}",
            owner=context.owner_user_id,
            agent_id=context.agent_id,
            thread_id=context.thread_id,
            run_id=context.run_id or context.context_id,
            context_id=context.context_id,
            kind="interaction",
            status="completed",
            payload={
                "action": action,
                "device_id": context.device_id,
                "session_id": params.get("session_id"),
            },
        )

    def device_receipt(
        self,
        context: ExecutionContext,
        operation_id: str,
        action: str,
        status: str,
        params: dict[str, Any],
        result: dict[str, Any] | None = None,
    ) -> None:
        # A late device receipt may outlive the chat/expert that originally
        # owned it; retain the device ledger without recreating deleted history.
        if context.agent_id:
            agent = self.repos.agent_repo.get(context.agent_id)
            if agent is None or agent.user_id != context.owner_user_id:
                return
        if context.thread_id:
            thread = self.repos.thread_repo.get(context.thread_id)
            if (
                thread is None
                or thread.user_id != context.owner_user_id
                or thread.agent_id != context.agent_id
            ):
                return
        summary: dict[str, Any] = {
            "operation_id": operation_id,
            "action": action,
            "device_id": context.device_id,
            "target_kind": context.target_kind,
            "working_dir": context.working_dir,
            "work_mode": context.work_mode,
        }
        for key in ("path", "source", "destination", "cwd", "job_id", "session_id", "transfer_id"):
            if isinstance(params.get(key), str):
                summary[key] = params[key][:4096]
        preview = command_preview_from_params(params)
        if preview:
            summary["command_preview"] = preview
        if result is not None:
            # A successful submission is not evidence that its Job has completed.
            # Keep stdout/stderr as bounded previews only (never full unbounded bodies).
            summary["receipt"] = bound_receipt_fields(result)
        self.events.save(
            event_id=f"operation:{operation_id}",
            owner=context.owner_user_id,
            agent_id=context.agent_id,
            thread_id=context.thread_id,
            run_id=context.run_id or context.context_id,
            context_id=context.context_id,
            kind="device",
            status=status,
            payload=summary,
        )

    def job_observation(self, context: ExecutionContext, result: dict[str, Any]) -> None:
        job_id, status = result.get("job_id"), result.get("status")
        if not isinstance(job_id, str) or not isinstance(status, str):
            return
        # A workbench reopened in a new context still observes the original Job.
        origin = ExecutionContextRepo(self.repos.db).get(
            context.owner_user_id, str(result.get("context_id") or "")
        )
        if origin is not None and (origin.target_kind, origin.device_id) == (
            context.target_kind,
            context.device_id,
        ):
            context = origin
        if context.thread_id:
            thread = self.repos.thread_repo.get(context.thread_id)
            if thread is None or (thread.user_id, thread.agent_id) != (
                context.owner_user_id,
                context.agent_id,
            ):
                return
        if context.agent_id:
            agent = self.repos.agent_repo.get(context.agent_id)
            if agent is None or agent.user_id != context.owner_user_id:
                return
        self.events.save(
            event_id=f"job:{context.context_id}:{job_id}",
            owner=context.owner_user_id,
            agent_id=context.agent_id,
            thread_id=context.thread_id,
            run_id=context.run_id or context.context_id,
            context_id=context.context_id,
            kind="job",
            status=status,
            payload={
                "device_id": context.device_id,
                "target_kind": context.target_kind,
                "job_id": job_id,
                "observation": {"status": "current", "observed_at": result.get("observed_at")},
                **{
                    key: result[key]
                    for key in (
                        "returncode",
                        "observed_at",
                        "updated_at",
                        "context_id",
                        "cancel_requested",
                        "cancel_incomplete",
                        "resources",
                    )
                    if key in result
                },
            },
        )

    def request_receipt(self, agent_id: str, snapshot: dict[str, Any]) -> None:
        self.events.save(
            event_id=f"request:{snapshot['request_id']}",
            owner=int(snapshot["owner_user_id"]),
            agent_id=agent_id,
            thread_id=str(snapshot["thread_id"]),
            run_id=str(snapshot.get("run_id") or snapshot["request_id"]),
            context_id=snapshot.get("context_id"),
            kind="model",
            status=str(snapshot["status"]),
            created_at=snapshot["created_at"],
            payload={
                key: snapshot[key]
                for key in (
                    "request_id",
                    "turn_id",
                    "model",
                    "estimated_input_tokens",
                    "actual_usage",
                    "duration_ms",
                    "ttft_ms",
                    "transformation",
                )
                if key in snapshot
            },
        )

    def tool_receipt(self, agent_id: str, event: dict[str, Any]) -> None:
        owner, thread_id, run_id = (
            int(event.get("owner_user_id") or 0),
            str(event.get("thread_id") or ""),
            str(event.get("run_id") or ""),
        )
        if not thread_id or not run_id:
            return
        thread = self.repos.thread_repo.get(thread_id)
        if thread is None or thread.user_id != owner or thread.agent_id != agent_id:
            raise OctopError(ErrorCode.NOT_FOUND, "run thread unavailable")
        self.events.save(
            event_id=str(event["event_id"]),
            owner=owner,
            agent_id=agent_id,
            thread_id=thread_id,
            run_id=run_id,
            context_id=event.get("context_id"),
            created_at=event["created_at"],
            kind=str(event["kind"]),
            status=str(event["status"]),
            payload={**event["payload"], "turn_id": event.get("turn_id")},
        )

    def list(
        self,
        owner: int,
        agent_id: str,
        thread_id: str,
        *,
        before: int | None = None,
        run_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        thread = self.repos.thread_repo.get(thread_id)
        if thread is None or thread.user_id != owner or thread.agent_id != agent_id:
            raise OctopError(ErrorCode.NOT_FOUND, "run history unavailable")
        rows = self.events.list(
            owner, agent_id, thread_id, before=before, run_id=run_id, limit=limit + 1
        )
        page = rows[:limit]
        return {
            "events": page,
            "has_more": len(rows) > limit,
            "next_before": page[-1]["seq"] if len(rows) > limit else None,
        }
