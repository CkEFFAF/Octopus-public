"""Safe provider failure categories, without persisting exception bodies."""

from __future__ import annotations

import json

from pydantic import ValidationError


def generation_error_code(exc: Exception) -> str:
    from octop.i18n.domains.stream import classify_model_error

    category = classify_model_error(exc)
    code = {
        "model_unavailable": "MODEL_UNAVAILABLE",
        "region_restricted": "REGION_RESTRICTED",
        "model_retired": "MODEL_RETIRED",
        "auth": "AUTH_FAILED",
        "access_denied": "ACCESS_DENIED",
        "insufficient_balance": "INSUFFICIENT_BALANCE",
        "rate_limit": "RATE_LIMITED",
        "provider_unavailable": "PROVIDER_UNAVAILABLE",
        "timeout_network": "TIMEOUT",
        "stream_stall": "TIMEOUT",
        "context_length": "INPUT_BUDGET",
    }.get(category.removeprefix("octop:stream_errors.") if category else "")
    if code:
        return f"METADATA_{code}"
    if isinstance(exc, ValueError) and str(exc) in {
        "METADATA_MODEL_UNAVAILABLE",
        "METADATA_INPUT_BUDGET",
    }:
        return str(exc)
    if isinstance(exc, (ValidationError, json.JSONDecodeError, ValueError)):
        return "METADATA_INVALID_OUTPUT"
    return "METADATA_GENERATION_FAILED"
