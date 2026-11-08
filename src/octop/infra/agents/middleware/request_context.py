"""Checkpoint durable context snapshots with stable model-facing replay."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain.agents.middleware import ModelRequest
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from octop_harness.middleware.memory_recall import (
    has_context_snapshot,
    replay_context_snapshots,
    stamp_context_snapshot,
)


def capture_context(state: Any, key: str, render: Callable[[], str]) -> dict[str, Any] | None:
    """Snapshot only the latest genuine user message, including an empty result."""
    messages = state.get("messages", [])
    message = next(
        (
            item
            for item in reversed(messages)
            if isinstance(item, HumanMessage)
            and item.additional_kwargs.get("lc_source") not in {"summarization", "pinned_skill"}
        ),
        None,
    )
    if message is None or has_context_snapshot(message, key):
        return None
    return {"messages": [stamp_context_snapshot(message, key, render())]}


def replay_context(request: ModelRequest[Any], key: str) -> list[AnyMessage]:
    """Append to API copies, validating against clean state before other replays.

    The Harness may already have appended its independent memory recall suffix.
    Never overwrite that copy or use its changed content to invalidate a valid
    snapshot. Edited checkpoint content still invalidates the old snapshot.
    """
    return replay_context_snapshots(
        list(request.messages), originals=request.state.get("messages", []), namespace=key
    )


def append_system_hint(request: ModelRequest[Any], hint: str) -> SystemMessage:
    original = request.system_message.content if request.system_message else ""
    content = (
        original + hint
        if isinstance(original, str)
        else [*original, {"type": "text", "text": hint}]
    )
    return SystemMessage(content=content)
