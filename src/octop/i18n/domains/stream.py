"""``stream_errors.*`` — user-facing guidance for chat / IM model failures."""

from __future__ import annotations

import re

from octop.i18n.loader import lookup, tr
from octop.infra.utils.locale import Locale

# Keep in sync with octop_harness.messages.MODEL_RETRY_FAILURE_MARK.
# Defined locally so Octop still imports on older harness wheels.
MODEL_RETRY_FAILURE_MARK = "[model_call_failed]"

_PREFIX = "octop:"

STREAM_STALL = f"{_PREFIX}stream_errors.stream_stall"
RATE_LIMIT = f"{_PREFIX}stream_errors.rate_limit"
AUTH = f"{_PREFIX}stream_errors.auth"
INSUFFICIENT_BALANCE = f"{_PREFIX}stream_errors.insufficient_balance"
CONTEXT_LENGTH = f"{_PREFIX}stream_errors.context_length"
RECURSION_LIMIT = f"{_PREFIX}stream_errors.recursion_limit"
TIMEOUT_NETWORK = f"{_PREFIX}stream_errors.timeout_network"
PROVIDER_UNAVAILABLE = f"{_PREFIX}stream_errors.provider_unavailable"
MODEL_CALL_FAILED = f"{_PREFIX}stream_errors.model_call_failed"
REGION_RESTRICTED = f"{_PREFIX}stream_errors.region_restricted"
MODEL_RETIRED = f"{_PREFIX}stream_errors.model_retired"
MODEL_UNAVAILABLE = f"{_PREFIX}stream_errors.model_unavailable"
ACCESS_DENIED = f"{_PREFIX}stream_errors.access_denied"
PATH_OUTSIDE_ROOT = f"{_PREFIX}stream_errors.path_outside_root"

__all__ = [
    "AUTH",
    "CONTEXT_LENGTH",
    "INSUFFICIENT_BALANCE",
    "MODEL_CALL_FAILED",
    "MODEL_RETRY_FAILURE_MARK",
    "PATH_OUTSIDE_ROOT",
    "PROVIDER_UNAVAILABLE",
    "RATE_LIMIT",
    "RECURSION_LIMIT",
    "STREAM_STALL",
    "TIMEOUT_NETWORK",
    "classify_model_error",
    "classify_stream_error_message",
    "exception_display_message",
    "format_stream_error",
    "model_retry_failure_prompt",
    "stream_error_message",
    "unwrap_model_retry_message",
]

_STRIP_PREFIXES = (
    "agent error:",
    "error:",
)

_RETRY_WRAPPER_RE = re.compile(
    r"(?is)^model call failed after \d+ attempts? with\s+",
)
_TECHNICAL_DETAIL_RE = re.compile(r"(?is)technical detail:\s*(.+)$")


def _normalize_message(message: str) -> str:
    msg = message.strip()
    lower = msg.lower()
    for prefix in _STRIP_PREFIXES:
        if lower.startswith(prefix):
            msg = msg[len(prefix) :].strip()
            lower = msg.lower()
            break
    return msg


def _format_template(key: str, locale: str | Locale, **kwargs: object) -> str:
    """Interpolate i18n text without treating exception braces as format fields."""
    escaped = {
        name: str(value).replace("{", "{{").replace("}", "}}") for name, value in kwargs.items()
    }
    return tr(key, locale, **escaped)


def _looks_like_send_file_tool_error(message: str) -> bool:
    """True for ``send_file_to_user`` path failures that should not look like a model outage."""
    return "send_file_to_user:" in _normalize_message(message).lower()


def unwrap_model_retry_message(message: str) -> str:
    """Strip retry-wrapper / recovery-prompt chrome so the inner error can be classified."""
    msg = _normalize_message(message)
    if MODEL_RETRY_FAILURE_MARK in msg:
        msg = msg.replace(MODEL_RETRY_FAILURE_MARK, " ").strip()
    tech = _TECHNICAL_DETAIL_RE.search(msg)
    if tech:
        return tech.group(1).strip()
    stripped = _RETRY_WRAPPER_RE.sub("", msg, count=1).strip()
    return stripped or msg


def classify_stream_error_message(message: str) -> str | None:
    """Return a stable ``octop:stream_errors.*`` key for known model failures."""
    msg = unwrap_model_retry_message(message)
    if not msg:
        return None
    if msg.startswith("octop:stream_errors.") and lookup(msg.removeprefix(_PREFIX), "en"):
        return msg
    lower = msg.lower()
    compact = lower.replace("_", "").replace(" ", "")

    # Tool / backend path jail — must not look like a model-provider outage.
    if "outside root directory" in lower or "path traversal not allowed" in lower:
        return PATH_OUTSIDE_ROOT

    if (
        "streamchunktimeouterror" in compact
        or "no streaming chunk received" in lower
        or "stream_chunk_timeout" in lower
    ):
        return STREAM_STALL

    if "regionerror" in compact or "not available in your country" in lower:
        return REGION_RESTRICTED
    if (
        "modeldeprecated" in compact
        or "has been deprecated" in lower
        or re.search(r"(?:http|error code:)\s*410\b", lower)
    ):
        return MODEL_RETIRED
    if re.search(r"(?:http|error code:)\s*404\b", lower):
        return MODEL_UNAVAILABLE
    if "endpoint is unavailable" in lower:
        return PROVIDER_UNAVAILABLE
    if re.search(r"(?:http|error code:)\s*403\b", lower) or "permissiondeniederror" in compact:
        return ACCESS_DENIED

    if (
        "error code: 429" in lower
        or "http 429" in lower
        or "rate_limit" in lower
        or "ratelimiterror" in compact
        or "too many requests" in lower
    ):
        return RATE_LIMIT

    if (
        "error code: 402" in lower
        or "http 402" in lower
        or "insufficient balance" in lower
        or "insufficient_quota" in lower
        or "insufficient credits" in lower
        or "exceeded your current quota" in lower
        or "payment_required" in lower
        or "billing_not_active" in lower
        or "arrearage" in lower
        or "余额不足" in msg
        or "账户余额" in msg
        or "欠费" in msg
    ):
        return INSUFFICIENT_BALANCE

    if (
        "error code: 401" in lower
        or "http 401" in lower
        or "invalid_api_key" in lower
        or "incorrect api key" in lower
        or "authenticationerror" in compact
        or ("unauthorized" in lower and ("api" in lower or "key" in lower))
    ):
        return AUTH

    if (
        "context_length_exceeded" in lower
        or "maximum context length" in lower
        or "prompt is too long" in lower
        or "input tokens exceed" in lower
        or "openaicontextoverflowerror" in compact
    ):
        return CONTEXT_LENGTH

    if (
        "graph_recursion_limit" in lower
        or "graphrecursionerror" in compact
        or "recursion limit of" in lower
        or (
            "recursion_limit" in lower and ("reached" in lower or "without hitting a stop" in lower)
        )
    ):
        return RECURSION_LIMIT

    if (
        "internalservererror" in compact
        or "bad gateway" in lower
        or "service unavailable" in lower
        or "error code: 500" in lower
        or "error code: 502" in lower
        or "error code: 503" in lower
        or "http 500" in lower
        or "http 502" in lower
        or "http 503" in lower
    ):
        return PROVIDER_UNAVAILABLE

    if (
        "timeouterror" in compact
        or "connectionerror" in compact
        or "timed out" in lower
        or "request timed out" in lower
        or "timed out or interrupted" in lower
        or "connection error" in lower
        or "apitimeouterror" in compact
        or "apiconnectionerror" in compact
    ):
        return TIMEOUT_NETWORK

    original = _normalize_message(message).lower()
    if "model call failed after" in original or MODEL_RETRY_FAILURE_MARK in original:
        return MODEL_CALL_FAILED

    return None


def classify_model_error(exc: BaseException | str) -> str | None:
    """Shared category for SDK exceptions, HTTP errors and legacy persisted strings.

    Inspect structured status/body first: SDK messages may be empty, and a 402
    from an upstream gateway does not necessarily mean the user's balance is low.
    Never return provider body text as user-facing diagnostics.
    """
    if isinstance(exc, BaseException):
        kind = type(exc).__name__.lower()
        if isinstance(exc, TimeoutError) or "timeout" in kind:
            return TIMEOUT_NETWORK
        if isinstance(exc, ConnectionError) or kind in {"connecterror", "apiconnectionerror"}:
            return TIMEOUT_NETWORK
    body = getattr(exc, "body", None)
    status = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    error = body.get("error", body) if isinstance(body, dict) else {}
    if isinstance(error, dict):
        kind = str(error.get("type") or error.get("code") or "")
        message = str(error.get("message") or "")
        category = classify_stream_error_message(f"{kind}: {message}")
        if category:
            return category
    category = classify_stream_error_message(exception_display_message(exc))
    if category:
        return category
    return (
        {
            404: MODEL_UNAVAILABLE,
            401: AUTH,
            402: INSUFFICIENT_BALANCE,
            403: ACCESS_DENIED,
            410: MODEL_RETIRED,
            429: RATE_LIMIT,
            500: PROVIDER_UNAVAILABLE,
            502: PROVIDER_UNAVAILABLE,
            503: PROVIDER_UNAVAILABLE,
            504: TIMEOUT_NETWORK,
        }.get(status)
        if isinstance(status, int)
        else None
    )


def _provider_payload(message: str) -> bool:
    """Recognize opaque provider payloads, including Python dict reprs."""
    return ("{" in message and "}" in message) or bool(
        re.search(r"(?:HTTP\s+[45]\d\d|error code:|api[_ ]?key|bearer\s+|sk-)", message, re.I)
    )


def exception_display_message(exc: BaseException | str) -> str:
    """Return ``str(exc)``, or the exception type name when the message is empty.

    Bare constructors like ``TimeoutError()`` / ``ConnectionError()`` yield
    ``str(exc) == ""``, which previously made probe logs and UI show nothing.
    Walk ``__cause__`` so wrapped empty wrappers still surface a root type.
    """
    if not isinstance(exc, BaseException):
        raw = str(exc).strip()
        return raw or "unknown error"
    raw = str(exc).strip()
    if raw:
        return raw
    cause: BaseException = exc
    while cause.__cause__ is not None:
        cause = cause.__cause__
    if cause is exc:
        return type(exc).__name__
    return f"{type(exc).__name__} <- {type(cause).__name__}"


def stream_error_message(error: str | None, locale: str | Locale = "en") -> str:
    """Localized stream / model error for user-facing chat and IM output."""
    if not error:
        return ""
    if error.startswith(_PREFIX):
        key = error.removeprefix(_PREFIX)
        if lookup(key, locale) is not None:
            return tr(key, locale)
    classified = classify_stream_error_message(error)
    if classified is not None:
        return tr(classified.removeprefix(_PREFIX), locale)
    if _provider_payload(error):
        return tr(MODEL_CALL_FAILED.removeprefix(_PREFIX), locale)
    return error


def format_stream_error(exc: BaseException | str, locale: str | Locale = "en") -> str:
    """Classify an exception or raw message; keep the actual cause when unknown.

    Tool / path failures (e.g. ``send_file_to_user`` missing file) pass through so
    the UI does not mislabel them as a model-call outage.
    """
    message = exception_display_message(exc)
    inner = unwrap_model_retry_message(message)
    classified = classify_model_error(exc)
    if classified is not None and classified != MODEL_CALL_FAILED:
        return tr(classified.removeprefix(_PREFIX), locale)
    if _looks_like_send_file_tool_error(message) or _looks_like_send_file_tool_error(inner):
        return message if _looks_like_send_file_tool_error(message) else inner
    if (
        inner
        and not _provider_payload(inner)
        and not (
            MODEL_RETRY_FAILURE_MARK in message
            or _RETRY_WRAPPER_RE.search(_normalize_message(message))
        )
    ):
        return _format_template("stream_errors.model_call_failed_detail", locale, detail=inner)
    return tr(MODEL_CALL_FAILED.removeprefix(_PREFIX), locale)


def model_retry_failure_prompt(exc: Exception, locale: str | Locale = "en") -> str:
    """Return a model-visible recovery prompt after retries are exhausted.

    Used as ``ModelRetryMiddleware.on_failure`` so the agent continues with a
    specific cause instead of raising a generic retry-exhausted exception.
    """
    classified = classify_model_error(exc) or MODEL_CALL_FAILED
    guidance = tr(classified.removeprefix(_PREFIX), locale)
    body = _format_template(
        "stream_errors.model_retry_prompt",
        locale,
        guidance=guidance,
        detail=classified,
    )
    return f"{MODEL_RETRY_FAILURE_MARK}\n{body}"
