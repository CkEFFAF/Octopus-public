"""Keep credentials out of server logs (query tokens + Authorization/Bearer)."""

from __future__ import annotations

import logging
import re

_QUERY_SECRET = re.compile(
    r"([?&](?:token|access_token|device_token|access_key|password|key)=)[^&#\s\"']*",
    re.IGNORECASE,
)

# Authorization: Bearer <jwt>  /  Authorization: <scheme> <secret>
_AUTHORIZATION = re.compile(
    r"(?i)\b(authorization\s*[:=]\s*)(bearer\s+)?([^\s\"']+)",
)

# Standalone Bearer tokens in log lines
_BEARER = re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9\-._~+/]+=*)")

# jwt_secret / common secret key assignments in log text
_NAMED_SECRET = re.compile(
    r"(?i)\b(jwt_secret|client_secret|api_secret|app_secret)\s*[=:]\s*([^\s\"']+)",
)

_SHARE_CAPABILITY = re.compile(r"((?:/api/public/thread-shares|/share)/)[^/?#\s\"']+")


def redact_secrets(message: str) -> str:
    """Return *message* with query tokens, Bearer, and named secrets masked."""
    out = _QUERY_SECRET.sub(r"\1[REDACTED]", message)
    out = _AUTHORIZATION.sub(r"\1\2[REDACTED]", out)
    out = _BEARER.sub(r"\1[REDACTED]", out)
    out = _NAMED_SECRET.sub(r"\1=[REDACTED]", out)
    out = _SHARE_CAPABILITY.sub(r"\1[REDACTED]", out)
    return out


class QuerySecretFilter(logging.Filter):
    """Historic name kept for imports; redacts query + Authorization/Bearer."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact_secrets(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


# Alias preferred for 0026+
SecretRedactionFilter = QuerySecretFilter


def install_query_secret_redaction() -> None:
    """Install after uvicorn configures its handlers, retaining ordinary logs."""
    for name in ("uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, QuerySecretFilter) for item in logger.filters):
            logger.addFilter(QuerySecretFilter())
