"""Conversation metadata adapters; identity is always the authenticated chat owner."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import Field

from octop.api.deps import current_user, get_server
from octop.api.routers.chat.serialize import _backfill_thread_projection
from octop.infra.conversations.models import (
    BriefPatch,
    ConversationBrief,
    DigestRequest,
    DigestResult,
    EventPage,
    JobView,
    MetadataJobRequest,
    SettingsPut,
    SettingsView,
    SourceView,
    TitleAction,
)
from octop.infra.conversations.service import ConversationService
from octop.infra.history.service import HistoryArchive

router = APIRouter()
SCOPE = "/agents/{agent_id}/threads/{thread_id}"


def conversation_service(server: Any) -> ConversationService:
    return ConversationService(
        server.app_runtime.agent_registry, server.services.config.default_timezone
    )


async def ensure_legacy_history(server: Any, user: Any, agent: str, thread: str) -> None:
    """Reuse the existing bounded legacy projection queue after authorization."""
    if isinstance(getattr(server.app_runtime, "history_archive", None), HistoryArchive):
        return
    repo = server.services.thread_message_repo
    if await asyncio.to_thread(repo.projection_status, thread) == "ready":
        return

    async def work() -> None:
        await _backfill_thread_projection(server, agent, thread, user=user)

    if server.app_runtime.gateway.history_backfill.enqueue(thread, work):
        await asyncio.to_thread(repo.mark_projection, thread, "queued")


@router.get(
    "/settings/conversation-metadata",
    summary="Conversation title and summary models",
    response_model=SettingsView,
)
async def metadata_settings(
    user: Any = Depends(current_user), server: Any = Depends(get_server)
) -> SettingsView:
    return await asyncio.to_thread(conversation_service(server).settings, user.id)


@router.put(
    "/settings/conversation-metadata",
    summary="Save account conversation metadata settings",
    response_model=SettingsView,
    description="Uses the signed-in account's providers. A stale settings revision returns 409.",
)
async def save_metadata_settings(
    body: SettingsPut, user: Any = Depends(current_user), server: Any = Depends(get_server)
) -> SettingsView:
    return await asyncio.to_thread(conversation_service(server).save_settings, user.id, body)


@router.get(
    SCOPE + "/brief",
    summary="Conversation overview and source coverage",
    response_model=ConversationBrief,
)
async def conversation_brief(
    agent_id: str,
    thread_id: str,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> ConversationBrief:
    return await asyncio.to_thread(conversation_service(server).brief, user.id, agent_id, thread_id)


@router.patch(
    SCOPE + "/brief",
    summary="Correct conversation goals or record acceptance",
    response_model=ConversationBrief,
    description="Changes only user-owned metadata. expected_revision prevents overwriting concurrent corrections.",
)
async def patch_brief(
    agent_id: str,
    thread_id: str,
    body: BriefPatch,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> ConversationBrief:
    return await asyncio.to_thread(
        conversation_service(server).patch, user.id, agent_id, thread_id, body
    )


@router.post(
    SCOPE + "/title-action",
    summary="Apply a title suggestion or restore automatic naming",
    response_model=ConversationBrief,
)
async def title_action(
    agent_id: str,
    thread_id: str,
    body: TitleAction,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> ConversationBrief:
    return await asyncio.to_thread(
        conversation_service(server).title_action,
        user.id,
        agent_id,
        thread_id,
        body.expected_revision,
        body.action,
        body.title,
    )


@router.post(
    SCOPE + "/metadata-jobs",
    summary="Generate a title suggestion or update the overview",
    response_model=JobView,
    status_code=202,
    description="Returns a durable, idempotent job. Title generation returns a suggestion; it does not unlock a manual title.",
)
async def start_metadata_job(
    agent_id: str,
    thread_id: str,
    body: MetadataJobRequest,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> JobView:
    await asyncio.to_thread(conversation_service(server).scope, user.id, agent_id, thread_id)
    await ensure_legacy_history(server, user, agent_id, thread_id)
    return await asyncio.to_thread(
        conversation_service(server).request,
        user.id,
        agent_id,
        thread_id,
        body.kind,
        body.command_id,
    )


@router.get(
    SCOPE + "/metadata-jobs/{job_id}",
    summary="Conversation generation job status",
    response_model=JobView,
)
async def get_metadata_job(
    agent_id: str,
    thread_id: str,
    job_id: str,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> JobView:
    return await asyncio.to_thread(
        conversation_service(server).job, user.id, agent_id, thread_id, job_id
    )


class BatchRequest(MetadataJobRequest):
    thread_ids: list[str] = Field(min_length=1, max_length=50)


@router.post(
    "/agents/{agent_id}/conversation-metadata-batch",
    summary="Organize selected historical conversations",
    response_model=list[JobView],
    status_code=202,
)
async def metadata_batch(
    agent_id: str,
    body: BatchRequest,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> list[JobView]:
    service = conversation_service(server)
    for thread in body.thread_ids:
        await asyncio.to_thread(service.scope, user.id, agent_id, thread)
    for thread in dict.fromkeys(body.thread_ids):
        await ensure_legacy_history(server, user, agent_id, thread)
    return [
        await asyncio.to_thread(
            service.request, user.id, agent_id, thread, body.kind, body.command_id
        )
        for thread in dict.fromkeys(body.thread_ids)
    ]


@router.get(
    SCOPE + "/events",
    summary="Conversation events within a server-timezone range",
    response_model=EventPage,
)
async def conversation_events(
    agent_id: str,
    thread_id: str,
    window: str = Query(default="today", max_length=80),
    cursor: str | None = Query(default=None, max_length=500),
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> EventPage:
    return await asyncio.to_thread(
        conversation_service(server).events, user.id, agent_id, thread_id, window, cursor
    )


@router.get(
    SCOPE + "/metadata-source",
    summary="Read an authorized original conversation source",
    response_model=SourceView,
)
async def metadata_source(
    agent_id: str,
    thread_id: str,
    kind: str = Query(max_length=30),
    id: str = Query(max_length=300),
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> SourceView:
    return await asyncio.to_thread(
        conversation_service(server).source, user.id, agent_id, thread_id, kind, id
    )


@router.post(
    SCOPE + "/digests",
    summary="Generate or reuse a conversation period summary",
    response_model=DigestResult | JobView,
    description="today, last_7d, or range:YYYY-MM-DD:YYYY-MM-DD (inclusive local dates). Empty ranges do not call a model.",
)
async def conversation_digest(
    agent_id: str,
    thread_id: str,
    body: DigestRequest,
    response: Response,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> DigestResult | JobView:
    value = await asyncio.to_thread(
        conversation_service(server).digest_request, user.id, agent_id, thread_id, body.window
    )
    if isinstance(value, JobView):
        response.status_code = 202
    return value


@router.get(
    SCOPE + "/digests/{digest_id}",
    summary="Read a generated summary and its coverage",
    response_model=DigestResult,
)
async def get_conversation_digest(
    agent_id: str,
    thread_id: str,
    digest_id: str,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> DigestResult:
    return await asyncio.to_thread(
        conversation_service(server).digest, user.id, agent_id, thread_id, digest_id
    )
