"""Owner share management and narrowly anonymous immutable snapshot reads."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from octop.api.deps import current_user, get_server
from octop.infra.history.sharing import DEFAULT_EXPIRY, ThreadSharingService

router = APIRouter()
SHARE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    "Referrer-Policy": "no-referrer",
}


class PublicMessage(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str


class SharePreview(BaseModel):
    preview_digest: str
    title: str
    timezone: str
    messages: list[PublicMessage]
    message_count: int


class CreateShareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    expires_in_seconds: int | None = Field(default=DEFAULT_EXPIRY, ge=60, le=31536000, strict=True)


class ShareRecord(BaseModel):
    share_id: str
    public_url: str | None
    public_path: str | None
    title: str
    agent_id: str
    thread_id: str
    created_at: float
    expires_at: float | None
    revoked_at: float | None
    status: Literal["active", "expired", "revoked"]
    message_count: int


class ShareList(BaseModel):
    shares: list[ShareRecord]
    next_before: str | None
    has_more: bool


class PublicSnapshot(BaseModel):
    title: str
    timezone: str
    created_at: float
    expires_at: float | None
    messages: list[PublicMessage]


def service(server: Any = Depends(get_server)) -> ThreadSharingService:
    runtime = server.app_runtime
    return ThreadSharingService(
        server.services.repos,
        server.services.config,
        runtime.agent_registry if runtime else None,
        getattr(runtime, "history_archive", None),
    )


def private_headers(response: Response) -> None:
    response.headers.update(SHARE_HEADERS)


@router.get(
    "/agents/{agent_id}/threads/{thread_id}/share-preview",
    response_model=SharePreview,
    summary="Preview exact public conversation snapshot",
)
async def preview_share(
    agent_id: str,
    thread_id: str,
    response: Response,
    user: Any = Depends(current_user),
    sharing: ThreadSharingService = Depends(service),
) -> dict[str, Any]:
    private_headers(response)
    return await sharing.preview(user.id, thread_id, agent_id=agent_id)


@router.post(
    "/agents/{agent_id}/threads/{thread_id}/shares",
    response_model=ShareRecord,
    status_code=201,
    summary="Publish reviewed conversation snapshot",
)
async def create_share(
    agent_id: str,
    thread_id: str,
    body: CreateShareBody,
    response: Response,
    user: Any = Depends(current_user),
    sharing: ThreadSharingService = Depends(service),
) -> dict[str, Any]:
    private_headers(response)
    return await sharing.create(
        user.id, thread_id, body.preview_digest, body.expires_in_seconds, agent_id=agent_id
    )


@router.get(
    "/agents/{agent_id}/threads/{thread_id}/shares",
    response_model=ShareList,
    summary="List your links for one conversation",
)
async def list_thread_shares(
    agent_id: str,
    thread_id: str,
    response: Response,
    before: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    user: Any = Depends(current_user),
    sharing: ThreadSharingService = Depends(service),
) -> dict[str, Any]:
    private_headers(response)
    return await asyncio.to_thread(
        sharing.list, user.id, thread_id=thread_id, agent_id=agent_id, before=before, limit=limit
    )


@router.get("/thread-shares", response_model=ShareList, summary="Manage all your public links")
async def list_shares(
    response: Response,
    before: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    user: Any = Depends(current_user),
    sharing: ThreadSharingService = Depends(service),
) -> dict[str, Any]:
    private_headers(response)
    return await asyncio.to_thread(sharing.list, user.id, before=before, limit=limit)


@router.delete("/thread-shares/{share_id}", status_code=204, summary="Close your public link")
async def revoke_share(
    share_id: str,
    user: Any = Depends(current_user),
    sharing: ThreadSharingService = Depends(service),
) -> Response:
    await asyncio.to_thread(sharing.revoke, user.id, share_id)
    return Response(status_code=204, headers=SHARE_HEADERS)


@router.get(
    "/public/thread-shares/{token}",
    response_model=PublicSnapshot,
    summary="Read an immutable public snapshot anonymously",
    description="Capability grants only this filtered snapshot. All unavailable links return 404.",
)
async def public_share(
    token: str,
    response: Response,
    sharing: ThreadSharingService = Depends(service),
) -> dict[str, Any]:
    private_headers(response)
    return await asyncio.to_thread(sharing.public, token)
