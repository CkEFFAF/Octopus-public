from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from octop.i18n.domains.stream import INSUFFICIENT_BALANCE, classify_model_error
from octop.infra.agents.model_retry import ChatModelRetryMiddleware
from octop.infra.utils.model_diagnostics import safe_diagnostics


@pytest.mark.asyncio
async def test_transient_retry_emits_wait_and_recovery_without_a_fake_answer(monkeypatch):
    events = []
    monkeypatch.setattr(
        "octop.infra.agents.model_retry.emit_retry_status", lambda **payload: events.append(payload)
    )
    expected = object()
    handler = AsyncMock(side_effect=[httpx.ReadTimeout("timeout"), expected])
    retry = ChatModelRetryMiddleware(
        max_retries=2, initial_delay=0, jitter=False, on_failure="error"
    )
    assert await retry.awrap_model_call(None, handler) is expected
    assert [event["phase"] for event in events] == ["waiting_retry", "retrying", "recovered"]
    assert events[1]["attempt"] == 2
    assert handler.await_count == 2


@pytest.mark.asyncio
async def test_http_429_exhausted_quota_is_not_retried():
    failure = RuntimeError("HTTP 429 insufficient_quota")
    assert classify_model_error(failure) == INSUFFICIENT_BALANCE
    handler = AsyncMock(side_effect=failure)
    with pytest.raises(RuntimeError):
        await ChatModelRetryMiddleware(max_retries=3).awrap_model_call(None, handler)
    assert handler.await_count == 1


@pytest.mark.asyncio
async def test_long_cooldown_returns_error_instead_of_an_invisible_sleep():
    failure = RuntimeError("HTTP 429 rate_limit")
    failure.response = SimpleNamespace(headers={"retry-after": "120"})
    handler = AsyncMock(side_effect=failure)
    with pytest.raises(RuntimeError):
        await ChatModelRetryMiddleware(max_retries=3, max_delay=10).awrap_model_call(None, handler)
    assert handler.await_count == 1


def test_http_date_retry_after_is_exposed_as_seconds(monkeypatch):
    monkeypatch.setattr("octop.infra.utils.model_diagnostics.time.time", lambda: 0)
    failure = RuntimeError("HTTP 429")
    failure.response = SimpleNamespace(headers={"retry-after": "Thu, 01 Jan 1970 00:00:20 GMT"})
    assert (
        safe_diagnostics(failure, code="rate", stage="chat", job_id="t")["retry_after_seconds"]
        == 20
    )


@pytest.mark.asyncio
async def test_cancelling_backoff_never_starts_the_next_model_attempt(monkeypatch):
    waiting = asyncio.Event()
    monkeypatch.setattr(
        "octop.infra.agents.model_retry.emit_retry_status", lambda **_payload: waiting.set()
    )
    handler = AsyncMock(side_effect=httpx.ReadTimeout("timeout"))
    task = asyncio.create_task(
        ChatModelRetryMiddleware(max_retries=2, initial_delay=30, max_delay=30).awrap_model_call(
            None, handler
        )
    )
    await asyncio.wait_for(waiting.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert handler.await_count == 1
