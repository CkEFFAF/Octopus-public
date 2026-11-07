"""Authenticated recovery of the original model response."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from octop.api.common.agent import assert_agent_access
from octop.api.deps import current_user, get_server
from octop.api.routers.chat.sse import format_sse
from octop.infra.agents.response_recovery import ResponseRecovery
from octop.infra.gateway.process.response_recovery import iter_response_recovery
from octop.infra.utils.locale import resolve_request_locale

router = APIRouter()


class ResponseRecoveryBody(BaseModel):
    model: str | None = Field(
        default=None,
        max_length=500,
        description="Optional owner-authorized replacement model; original context is retained",
    )
    response_id: str = Field(
        min_length=1, max_length=160, description="Server-issued identity of the original response"
    )
    command_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-zA-Z0-9_.:-]+$",
        description="Stable retry identity, reused after an uncertain network result",
    )


class ResponseRecoveryOut(BaseModel):
    response_id: str
    retry_at: float
    action: str


@router.get(
    "/agents/{agent_id}/threads/{thread_id}/response-recovery",
    response_model=ResponseRecoveryOut,
    summary="Inspect whether the latest answer can be recovered without resending its question",
)
async def response_recovery(
    agent_id: str,
    thread_id: str,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    assert_agent_access(server, agent_id, user)
    return await ResponseRecovery(server.app_runtime.agent_registry).latest(
        int(user.id), agent_id, thread_id
    )


@router.post(
    "/agents/{agent_id}/threads/{thread_id}/response-recovery",
    summary="Recover the original answer from its model checkpoint (SSE)",
    description="Reuses the original message and attachments. Rejects stale checkpoints and never replays a completed tool step. command_id deduplicates uncertain retries.",
)
async def recover_response(
    agent_id: str,
    thread_id: str,
    body: ResponseRecoveryBody,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> StreamingResponse:
    assert_agent_access(server, agent_id, user)
    manager = server.app_runtime.agent_registry
    await asyncio.to_thread(ResponseRecovery(manager).authorize, int(user.id), agent_id, thread_id)
    locale = resolve_request_locale(request)

    async def events() -> Any:
        async for frame in iter_response_recovery(
            manager=manager,
            processor=server.app_runtime.gateway.processor,
            owner=int(user.id),
            agent=agent_id,
            thread=thread_id,
            response_id=body.response_id,
            command_id=body.command_id,
            locale=locale,
            model=body.model,
        ):
            yield format_sse("message", frame)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
