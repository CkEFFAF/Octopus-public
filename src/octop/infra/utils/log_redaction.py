"""Keep credentials carried in HTTP/WebSocket query strings out of server logs."""

from __future__ import annotations

import logging
import re

_QUERY_SECRET = re.compile(
    r"([?&](?:token|access_token|device_token|access_key|password|key)=)[^&#\s\"']*",
    re.IGNORECASE,
)


class QuerySecretFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = _QUERY_SECRET.sub(r"\1[REDACTED]", message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def install_query_secret_redaction() -> None:
    """Install after uvicorn configures its handlers, retaining ordinary logs."""
    for name in ("uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, QuerySecretFilter) for item in logger.filters):
            logger.addFilter(QuerySecretFilter())
