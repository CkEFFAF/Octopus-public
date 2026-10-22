"""Bounded public-message extraction; never reads files or hidden reasoning."""

from __future__ import annotations

import json
from typing import Any

from octop.infra.utils.llm_text import strip_thinking


def public_text(value: Any) -> str:
    if isinstance(value, str):
        return strip_thinking(value)
    if isinstance(value, list):
        return strip_thinking(
            "\n".join(
                public_text(item) if isinstance(item, str) else str(item.get("text", ""))
                for item in value
                if isinstance(item, str)
                or (
                    isinstance(item, dict)
                    and item.get("type") in {"text", "input_text", "output_text"}
                )
            )
        )
    return ""


def message_source(
    row: dict[str, Any], offset: int = 0, budget: int = 12000
) -> tuple[dict[str, Any], int]:
    wire = json.loads(row["message_json"])
    data = wire.get("data", wire)
    text = public_text(data.get("content", data.get("text", "")))
    # UTF-8 bytes are a conservative token budget for the configured text adapters.
    raw = text[offset:].encode("utf-8")[:budget]
    part = raw.decode("utf-8", errors="ignore")
    consumed = offset + len(part)
    stamp = float(row["created_at"])
    if stamp > 100_000_000_000:
        stamp /= 1000
    return {
        "ref": {"kind": "message", "id": str(row.get("ref_id") or row["seq"])},
        "role": "user" if row["role"] in {"user", "human"} else "assistant",
        "text": part,
        "occurred_at": stamp,
        "offset": offset,
        "partial": consumed < len(text),
    }, consumed if consumed < len(text) else 0


def output_json(text: str) -> dict[str, Any]:
    text = strip_thinking(text).strip()
    if text.startswith("```json") and text.endswith("```"):
        text = text[7:-3].strip()
    elif text.startswith("```") and text.endswith("```"):
        text = text[3:-3].strip()
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError("METADATA_INVALID_OUTPUT")
    return result
