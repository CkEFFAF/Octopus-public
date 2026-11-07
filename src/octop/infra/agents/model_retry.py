"""Bounded, observable model retries; never turn failures into assistant replies."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from langchain.agents.middleware import ModelRetryMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage
from langgraph.config import get_stream_writer
from langgraph.errors import GraphBubbleUp

from octop.i18n.domains.stream import (
    PROVIDER_UNAVAILABLE,
    RATE_LIMIT,
    STREAM_STALL,
    TIMEOUT_NETWORK,
    classify_model_error,
)
from octop.infra.utils.model_diagnostics import safe_diagnostics

TRANSIENT_MODEL_ERRORS = frozenset(
    {RATE_LIMIT, TIMEOUT_NETWORK, PROVIDER_UNAVAILABLE, STREAM_STALL}
)


class ModelCallFailure(RuntimeError):
    """A real failure understood by Harness job supervision, with safe SDK metadata."""

    def __init__(self, code: str, original: Exception) -> None:
        super().__init__(code)
        self.response = getattr(original, "response", None)
        self.status_code = getattr(original, "status_code", None)
        self.request_id = getattr(original, "request_id", None)


def emit_retry_status(**payload: Any) -> None:
    # Non-streaming calls have no custom stream writer.
    with suppress(RuntimeError):
        get_stream_writer()({"octop_model_retry": payload})


def retryable_model_error(exc: Exception) -> bool:
    return classify_model_error(exc) in TRANSIENT_MODEL_ERRORS


class ChatModelRetryMiddleware(ModelRetryMiddleware[Any, Any]):
    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any] | AIMessage:
        try:
            return super().wrap_model_call(request, handler)
        except GraphBubbleUp:
            raise
        except Exception as exc:
            if code := classify_model_error(exc):
                raise ModelCallFailure(code, exc) from exc
            raise

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any] | AIMessage:
        for attempt in range(self.max_retries + 1):
            if attempt:
                emit_retry_status(
                    phase="retrying", attempt=attempt + 1, max_attempts=self.max_retries + 1
                )
            try:
                result = await handler(request)
                if attempt:
                    emit_retry_status(
                        phase="recovered", attempt=attempt + 1, max_attempts=self.max_retries + 1
                    )
                return result
            except GraphBubbleUp:
                raise
            except Exception as exc:
                code = classify_model_error(exc)
                if code not in TRANSIENT_MODEL_ERRORS or attempt >= self.max_retries:
                    if code:
                        raise ModelCallFailure(code, exc) from exc
                    raise
                diagnostic = safe_diagnostics(exc, code=code, stage="chat", job_id="")
                hint = float(diagnostic.get("retry_after_seconds") or 0)
                # A long provider cooldown belongs in the recoverable notice,
                # not an invisible sleep which occupies the conversation.
                if hint > self.max_delay:
                    raise ModelCallFailure(code, exc) from exc
                delay = min(self.initial_delay * self.backoff_factor**attempt, self.max_delay)
                if self.jitter:
                    delay = min(delay * random.uniform(0.75, 1.25), self.max_delay)
                delay = max(delay, hint)
                emit_retry_status(
                    phase="waiting_retry",
                    attempt=attempt + 1,
                    max_attempts=self.max_retries + 1,
                    retry_at=time.time() + delay,
                    error_code=code,
                )
                await asyncio.sleep(delay)
        raise RuntimeError("Unreachable model retry state")
