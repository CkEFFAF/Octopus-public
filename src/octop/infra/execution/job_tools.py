"""Agent Job operations use the same request target as standard project tools."""

from __future__ import annotations

import base64
import json
from typing import Annotated, Any

from langchain_core.tools import ToolException, tool
from langgraph.config import get_config
from pydantic import StringConstraints

from octop.i18n import tr
from octop.infra.execution.backend import RequestExecutionBackend


def build_job_tools(backend: RequestExecutionBackend) -> list[Any]:
    @tool
    async def job_start(
        argv: list[str],
        idempotency_key: str,
        title: Annotated[
            str,
            StringConstraints(
                strip_whitespace=True, min_length=1, max_length=120, pattern=r"^[^\x00-\x1f\x7f]+$"
            ),
        ],
        cwd: str | None = None,
        notify_on_exit: bool = True,
        progress_hook_id: str | None = None,
    ) -> str:
        """Start a persistent Job on the selected device, independent of chat and connection lifetime.

        Reuse the same idempotency_key when checking an uncertain submission;
        changing argv/cwd with that key is rejected. Returns acceptance/status,
        not experiment completion. Use job_status and job_logs to observe it.
        title is a short, meaningful task name in the user's language (for example,
        "CPS validation probes"), never a shell name such as bash. Return to the user
        after acceptance. By default one read-only follow-up is scheduled in this
        original conversation when a real terminal receipt arrives; do not sleep
        or repeatedly poll. Set notify_on_exit=False only when no follow-up is wanted.
        To show real progress, first register_wakeup_hook(delivery_mode="progress"),
        instrument the script with its callback, and pass its hook_id as progress_hook_id.
        Ordinary stdout does not imply a percentage. Do not invent progress estimates.
        """
        if title.lower().replace(" ", "") in {
            "bash",
            "sh",
            "runbash",
            "运行bash",
            "后台任务",
            "backgroundtask",
            "job",
        }:
            cfg = get_config().get("configurable") or {}
            raise ToolException(tr("execution.jobTitleRequired", str(cfg.get("language") or "en")))
        return json.dumps(
            await backend.call_operation(
                "jobs.start",
                {
                    "argv": argv,
                    "cwd": cwd,
                    "idempotency_key": idempotency_key,
                    "title": title,
                    "notify_on_exit": notify_on_exit,
                    "progress_hook_id": progress_hook_id,
                },
            ),
            ensure_ascii=False,
        )

    @tool
    async def job_status(job_id: str | None = None, offset: int = 0) -> str:
        """Inspect a persistent Job's real process receipt/resources, or list this device's Jobs.

        Offline or unknown is not success. CPU counters and RSS describe the
        command process; unavailable measurements are not inferred. List command
        previews are bounded; inspect an individual Job for its full argv, and
        use next_offset to continue a listing.
        """
        return json.dumps(
            await backend.call_operation(
                "jobs.status" if job_id else "jobs.list", {"job_id": job_id, "offset": offset}
            ),
            ensure_ascii=False,
        )

    @tool
    async def job_logs(job_id: str, offset: int = 0, length: int = 8192) -> str:
        """Read incremental, bounded Job stdout/stderr. Continue from next_offset.

        Output beyond the retained log budget is marked truncated; do not put
        all training logs into the model context.
        """
        result = await backend.call_operation(
            "jobs.logs", {"job_id": job_id, "offset": offset, "length": length}
        )
        data = result.pop("data_b64")
        return json.dumps(
            {**result, "text": base64.b64decode(data).decode("utf-8", errors="replace")},
            ensure_ascii=False,
        )

    @tool
    async def job_cancel(job_id: str) -> str:
        """Request Job cancellation. Report stopped only after job_status confirms a final receipt."""
        return json.dumps(
            await backend.call_operation("jobs.cancel", {"job_id": job_id}), ensure_ascii=False
        )

    job_start.handle_tool_error = True
    from octop.infra.execution.wakeup_tools import build_wakeup_tools

    return [job_start, job_status, job_logs, job_cancel, *build_wakeup_tools(backend)]
