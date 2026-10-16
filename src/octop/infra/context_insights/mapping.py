"""Map trajectory / run-event kinds onto Insights chip vocabulary."""

from __future__ import annotations

from typing import Any

# Chip vocabulary aligned with dsh-context Events (spec 0020 §1.2 / S2).
MAPPED_KINDS = (
    "inject",
    "compact",
    "prune",
    "switch",
    "mode",
    "model",
    "user",
    "assistant",
    "tool",
    "other",
)

_TRAJECTORY_MAP: dict[str, str] = {
    "compacted": "compact",
    "context": "inject",
    "system": "inject",
    "user": "user",
    "assistant": "assistant",
    "tool": "tool",
}

_RUN_EVENT_MAP: dict[str, str] = {
    "model": "model",
    "device": "switch",
    "workflow": "mode",
    "job": "other",
    "interaction": "other",
}


def map_event_kind(
    raw_kind: str,
    *,
    payload: dict[str, Any] | None = None,
    source: str = "trajectory",
) -> str:
    """Return a mapped_kind chip label; never invent evidence fields."""
    kind = (raw_kind or "").strip().lower()
    data = payload or {}
    if source == "run_event":
        mapped = _RUN_EVENT_MAP.get(kind)
        if mapped:
            return mapped
        mode = str(data.get("work_mode") or data.get("conversation_mode") or "").strip()
        if mode:
            return "mode"
        return "other"
    mapped = _TRAJECTORY_MAP.get(kind)
    if mapped == "compact":
        return "compact"
    transform = data.get("transformation") if isinstance(data.get("transformation"), dict) else None
    if transform and str(transform.get("kind") or "") in {"summarization", "message_rewrite", "prune"}:
        return "compact" if transform.get("kind") != "prune" else "prune"
    if str(data.get("prune") or data.get("pruned") or "").lower() in {"1", "true", "yes"}:
        return "prune"
    producer = str(data.get("producer") or data.get("source") or "").lower()
    if "model" in producer or kind == "model":
        return "model"
    if kind in {"mode", "switch"}:
        return kind
    return mapped if mapped in MAPPED_KINDS else "other"
