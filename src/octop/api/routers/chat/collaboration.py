"""Owner-authorized collaboration receipts, working messages and resources."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

from octop.api.deps import current_user, get_server
from octop.infra.agents.teams.collaboration import CollaborationService
from octop.infra.documents.resources import ResourceService

router = APIRouter()


class InvocationOut(BaseModel):
    invocation_id: str
    source_agent_id: str
    callee_agent_id: str
    source_thread_id: str
    child_thread_id: str | None
    root_run_id: str
    parent_invocation_id: str | None
    retry_of: str | None
    transport_status: str
    task_outcome: str
    target_policy: str
    requested_target: dict[str, Any]
    resolved_target: dict[str, Any] | None
    error_code: str | None
    retryable: bool
    prompt: str
    resource_ids: list[str] = Field(default_factory=list)
    created_at: float
    updated_at: float


class ResourceOut(BaseModel):
    resource_id: str
    version: str
    name: str
    media_type: str
    size: int
    source_agent_id: str
    source_thread_id: str | None
    source_kind: str
    source_device_id: str | None
    parse_state: str
    publication_state: str
    content_url: str
    download_url: str
    delivery_status: str | None = None
    error_code: str | None = None
    created_at: float


class EventOut(BaseModel):
    seq: int
    event_id: str
    event_type: str
    invocation_id: str | None
    resource_id: str | None
    payload: dict[str, Any]
    created_at: float


class CollaborationOut(BaseModel):
    invocations: list[InvocationOut]
    events: list[EventOut]
    artifacts: list[ResourceOut]
    next_cursor: int
    has_more: bool


class WorkingMessageOut(BaseModel):
    seq: int
    role: str
    content: str
    created_at: float


class CollaborationDetailOut(BaseModel):
    invocation: InvocationOut
    messages: list[WorkingMessageOut]
    has_more: bool
    next_before: int | None


@router.get(
    "/agents/{agent_id}/threads/{thread_id}/collaboration",
    response_model=CollaborationOut,
    summary="Inspect persistent collaboration and replay events",
)
async def collaboration(
    agent_id: str,
    thread_id: str,
    after: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    service = CollaborationService(server.app_runtime.agent_registry)
    return await asyncio.to_thread(service.listing, int(user.id), agent_id, thread_id, after, limit)


@router.get(
    "/agents/{agent_id}/threads/{thread_id}/collaboration/{invocation_id}",
    response_model=CollaborationDetailOut,
    summary="Inspect one delegation and public child messages",
)
async def collaboration_detail(
    agent_id: str,
    thread_id: str,
    invocation_id: str,
    before_seq: int | None = Query(None, ge=1),
    limit: int = Query(40, ge=1, le=100),
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    service = CollaborationService(server.app_runtime.agent_registry)
    return await asyncio.to_thread(
        service.detail, int(user.id), agent_id, thread_id, invocation_id, before_seq, limit
    )


@router.get(
    "/agents/{agent_id}/threads/{thread_id}/resources/{resource_id}",
    response_model=ResourceOut,
    summary="Inspect a resource version",
)
async def resource_metadata(
    agent_id: str,
    thread_id: str,
    resource_id: str,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    service = ResourceService(server.app_runtime.agent_registry)
    resource = await asyncio.to_thread(
        service.owner_view, int(user.id), agent_id, thread_id, resource_id
    )
    return service.public(resource, agent_id, thread_id)


@router.get(
    "/agents/{agent_id}/threads/{thread_id}/resources/{resource_id}/content",
    summary="Preview or download verified resource bytes",
)
async def resource_content(
    agent_id: str,
    thread_id: str,
    resource_id: str,
    download: bool = False,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Response:
    service = ResourceService(server.app_runtime.agent_registry)
    resource = await asyncio.to_thread(
        service.owner_view, int(user.id), agent_id, thread_id, resource_id
    )
    data = await service.bytes(int(user.id), resource)
    disposition = "attachment" if download else "inline"
    return Response(
        data,
        media_type=resource["media_type"],
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(resource['name'], safe='')}",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
            "Cache-Control": "private, no-store",
        },
    )
