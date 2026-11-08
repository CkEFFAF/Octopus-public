"""Single-event capability credentials, separate from account and Agent tokens."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from octop.api.deps import get_server
from octop.infra.execution.wakeup_hooks import WakeupHookService

router = APIRouter()


class WakeupEventBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: str = Field(
        min_length=1,
        max_length=100,
        description="Custom event name matching the registered callback.",
    )
    data: Any = Field(
        default=None,
        description="Any JSON value, at most 8192 encoded bytes. No domain-specific fields are required.",
    )


class WakeupEventReceipt(BaseModel):
    accepted: bool
    duplicate: bool
    hook_id: str


@router.post(
    "/wakeup-hooks/{hook_id}/fire",
    status_code=202,
    response_model=WakeupEventReceipt,
    summary="Signal one registered expert callback",
    description="Uses only the scoped X-Octop-Wakeup-Token credential returned during registration. Queues feedback in the original conversation and returns without waiting for the model. Repeated delivery is idempotent.",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": WakeupEventBody.model_json_schema()}},
        }
    },
)
async def fire_wakeup_hook(
    hook_id: str,
    request: Request,
    hook_token: str = Header(default="", alias="X-Octop-Wakeup-Token"),
    server: Any = Depends(get_server),
) -> Any:
    hooks = WakeupHookService(server.app_runtime.execution)
    await asyncio.to_thread(hooks.authenticate, hook_id, hook_token)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 12288:
            raise HTTPException(413, "Event body is too large")
    try:
        body = WakeupEventBody.model_validate_json(raw)
        return await asyncio.to_thread(hooks.fire, hook_id, hook_token, body.event_type, body.data)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, "Invalid event name or JSON data") from exc
