"""Agent-facing registration and inspection for arbitrary named events."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import ToolException, tool
from langgraph.config import get_config

from octop.infra.errors import OctopError
from octop.infra.execution.backend import RequestExecutionBackend
from octop.infra.execution.wakeup_hooks import WakeupHookService


def build_wakeup_tools(backend: RequestExecutionBackend) -> list[Any]:
    def scope() -> tuple[int, str, str | None]:
        cfg = get_config().get("configurable") or {}
        owner, thread = int(cfg.get("user") or 0), str(cfg.get("thread_id") or "")
        if not owner or not thread:
            raise ToolException("A wakeup hook requires an authenticated conversation.")
        context = cfg.get("octop_execution_context") or {}
        return owner, thread, context.get("context_id")

    hooks = WakeupHookService(backend.executions)

    @tool
    async def register_wakeup_hook(
        title: str,
        event_type: str,
        purpose: str,
        idempotency_key: str,
        expires_in: int = 604800,
        delivery_mode: str = "wake",
    ) -> str:
        """Register a single-use callback for ANY custom event, bound to this expert and conversation.

        event_type is your own event name, not a fixed list: build.done, file.ready,
        external.alert, or any other meaningful event. title and purpose use the
        user's language. purpose states what to inspect/report when awakened.
        No experiment, training, metric, or other domain-specific fields are required.
        The callback accepts {"event_type": "your.name", "data": <any JSON value up to 8192 bytes>}.
        POST to callback_url with the X-Octop-Wakeup-Token header. A script may use
        Python requests or curl. Keep the token private; it authorizes only this
        registered event, never arbitrary chat/commands. Duplicates do not wake twice.
        expires_in is 60..2592000 seconds. Reuse the idempotency_key on retries.
        Return to the user immediately; do not sleep waiting for the event.

        For ongoing command progress use delivery_mode="progress" instead of "wake".
        Register BEFORE job_start, then pass the returned hook_id as progress_hook_id.
        Instrument the script to POST data={"percent": 35, "phase": "Validation",
        "message": "70 of 200 files", "sequence": 2}. percent is optional, 0..100;
        omit it when unknown. phase/message use the user's language. Increase sequence
        on each update to reject stale retries. Send done=true on the final update.
        Progress updates only refresh the UI and never invoke the model. Use a separate
        wake hook for a key event, or job_start's default terminal notification.
        """
        owner, thread, context = scope()
        try:
            return json.dumps(
                hooks.register(
                    owner,
                    backend.agent_id,
                    thread,
                    context,
                    title=title,
                    event_type=event_type,
                    purpose=purpose,
                    idempotency_key=idempotency_key,
                    expires_in=expires_in,
                    delivery_mode=delivery_mode,
                ),
                ensure_ascii=False,
            )
        except (ValueError, OctopError) as exc:
            raise ToolException(str(exc)) from exc

    @tool
    async def wakeup_hook_status(hook_id: str | None = None) -> str:
        """Inspect this conversation's event callbacks, their purpose, expiry and actual state."""
        owner, thread, _ = scope()
        return json.dumps(
            hooks.inspect(owner, backend.agent_id, thread, hook_id), ensure_ascii=False
        )

    @tool
    async def cancel_wakeup_hook(hook_id: str) -> str:
        """Cancel this conversation's callback before dispatch. A running callback returns running.

        Cancellation does not stop its script, job, or an already dispatched analysis.
        """
        owner, thread, _ = scope()
        return json.dumps(
            hooks.cancel(owner, backend.agent_id, thread, hook_id), ensure_ascii=False
        )

    for item in [register_wakeup_hook, wakeup_hook_status, cancel_wakeup_hook]:
        item.handle_tool_error = True
    return [register_wakeup_hook, wakeup_hook_status, cancel_wakeup_hook]
