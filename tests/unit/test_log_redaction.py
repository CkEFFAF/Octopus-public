from __future__ import annotations

import logging

import pytest

from octop.infra.utils.log_redaction import QuerySecretFilter


@pytest.mark.parametrize(
    "path",
    [
        "/api/notifications/ws?token=private.jwt&topic=devices",
        "/api/desktop/ws?TOKEN=private.jwt&screen=1",
        "/api/file?name=report&access_key=oak_private&key=private",
    ],
)
def test_query_credentials_are_redacted_without_removing_request_context(path: str) -> None:
    record = logging.LogRecord(
        "uvicorn.error", logging.INFO, __file__, 1, "WebSocket %s [accepted]", (path,), None
    )
    assert QuerySecretFilter().filter(record)
    output = record.getMessage()
    assert "private" not in output
    assert "[REDACTED]" in output
    assert "[accepted]" in output
    assert output.startswith("WebSocket /api/")


def test_ordinary_log_formatting_is_retained() -> None:
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, "GET %s %d", ("/api/health", 200), None
    )
    assert QuerySecretFilter().filter(record)
    assert record.args == ("/api/health", 200)
    assert record.getMessage() == "GET /api/health 200"


@pytest.mark.parametrize(
    "path",
    [
        "/api/notifications?token=private.jwt",
        "/api/public/thread-shares/private-capability",
        "/share/private-capability",
    ],
)
def test_uvicorn_access_formatter_retains_structured_redacted_arguments(path: str) -> None:
    from uvicorn.logging import AccessFormatter

    args = ("127.0.0.1:1234", "GET", path, "1.1", 200)
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', args, None
    )
    assert QuerySecretFilter().filter(record)
    output = AccessFormatter(
        '%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False
    ).format(record)
    assert "private" not in output
    assert "[REDACTED]" in output
    assert "GET /" in output and "HTTP/1.1" in output and "200 OK" in output
    assert isinstance(record.args, tuple) and len(record.args) == 5


@pytest.mark.parametrize(
    "message",
    [
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.private.sig",
        "authorization=Bearer secret-token-value",
        "Bearer eyJhbGciOiJIUzI1NiJ9.abc.def",
        "jwt_secret=super-secret-value",
    ],
)
def test_authorization_and_bearer_are_redacted(message: str) -> None:
    from octop.infra.utils.log_redaction import redact_secrets

    out = redact_secrets(message)
    assert "private" not in out.lower() or "[REDACTED]" in out
    assert "super-secret-value" not in out
    assert "secret-token-value" not in out
    assert "[REDACTED]" in out
