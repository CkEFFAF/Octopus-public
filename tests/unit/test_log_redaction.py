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
