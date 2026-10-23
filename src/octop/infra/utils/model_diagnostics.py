"""Content-free diagnostics that can safely be persisted and copied by an owner."""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

FIELDS = frozenset(
    [
        "title",
        "one_liner",
        "objective",
        "scope",
        "stage",
        "constraints",
        "completed",
        "in_progress",
        "remaining",
        "blockers",
        "next_actions",
        "decisions",
        "findings",
        "events",
        "new_objective",
        "text",
        "source_refs",
        "kind",
        "id",
        "revision",
        "summary",
    ]
)


def output_issues(exc: ValidationError) -> list[dict[str, str]]:
    return [
        {
            "path": ".".join(
                str(p) if isinstance(p, int) or p in FIELDS else "<field>" for p in e["loc"]
            ),
            "type": e["type"],
        }
        for e in exc.errors(include_input=False, include_url=False)[:12]
    ]


def safe_diagnostics(exc: Exception, *, code: str, stage: str, job_id: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "code": code,
        "exception": type(exc).__name__,
        "stage": stage,
        "job_id": job_id,
    }
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        result["http_status"] = status
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", {}) or {}
    retry_after = str(headers.get("retry-after", ""))
    if retry_after.isdigit():
        result["retry_after_seconds"] = min(int(retry_after), 86400)
    request_id = getattr(exc, "request_id", None) or headers.get("x-request-id")
    if isinstance(request_id, str) and re.fullmatch(r"[a-zA-Z0-9_.:-]{1,100}", request_id):
        result["request_id"] = request_id
    if isinstance(exc, ValidationError):
        result["issues"] = output_issues(exc)
    elif str(exc) == "METADATA_INPUT_BUDGET":
        for key in (
            "input_bytes",
            "input_limit_bytes",
            "input_tokens_estimate",
            "input_limit_tokens",
        ):
            value = getattr(exc, key, None)
            if isinstance(value, int) and 0 <= value <= 1_000_000_000:
                result[key] = value
    elif str(exc) == "METADATA_OUTPUT_TRUNCATED":
        result["format_failure"] = "output_token_limit"
    elif code == "METADATA_INVALID_OUTPUT":
        result["format_failure"] = (
            "invalid_json"
            if type(exc).__name__ == "JSONDecodeError"
            else "invalid_source_reference_or_shape"
        )
    return result
