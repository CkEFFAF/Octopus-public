"""Agent Job operations use the same request target as standard project tools."""

from __future__ import annotations

import base64
import json
from typing import Any

from langchain_core.tools import tool

from octop.infra.execution.backend import RequestExecutionBackend


def build_job_tools(backend: RequestExecutionBackend) -> list[Any]:
    @tool
    async def job_start(argv: list[str], idempotency_key: str, cwd: str | None = None) -> str:
        """Start a persistent Job on the selected device, independent of chat and connection lifetime.

        Reuse the same idempotency_key when checking an uncertain submission;
        changing argv/cwd with that key is rejected. Returns acceptance/status,
        not experiment completion. Use job_status and job_logs to observe it.
        """
        return json.dumps(
            await backend.call_operation(
                "jobs.start", {"argv": argv, "cwd": cwd, "idempotency_key": idempotency_key}
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

    return [job_start, job_status, job_logs, job_cancel]
