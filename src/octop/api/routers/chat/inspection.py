"""Authenticated request snapshot history and bounded component detail."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from octop.api.deps import current_user, get_server
from octop.infra.execution.events import RunInspectionService
from octop.infra.execution.inspection import RequestInspectionService

router = APIRouter()


class WorkflowDecisionBody(BaseModel):
    version: int = Field(ge=0)
    choice: int = Field(ge=0, le=4)


@router.post(
    "/agents/{agent_id}/threads/{thread_id}/workflows/{event_id}/decision",
    summary="Resolve a cowork decision as the account owner",
)
async def decide_workflow(
    agent_id: str,
    thread_id: str,
    event_id: str,
    body: WorkflowDecisionBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    import asyncio

    from octop.infra.execution.work_mode import WorkModeService

    return await asyncio.to_thread(
        WorkModeService(server.services.repos).decide,
        int(user.id),
        agent_id,
        thread_id,
        event_id,
        version=body.version,
        choice=body.choice,
    )


@router.get(
    "/agents/{agent_id}/threads/{thread_id}/run-events", summary="Inspect correlated run receipts"
)
async def list_run_events(
    agent_id: str,
    thread_id: str,
    before: int | None = Query(None, ge=1),
    run_id: str | None = None,
    limit: int = Query(100, ge=1, le=200),
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    import asyncio

    return await asyncio.to_thread(
        RunInspectionService(server.services.repos).list,
        int(user.id),
        agent_id,
        thread_id,
        before=before,
        run_id=run_id,
        limit=limit,
    )


class RequestSnapshotOut(BaseModel):
    request_id: str
    seq: int
    status: str
    created_at: float
    thread_id: str
    agent_id: str
    context_id: str | None = None
    turn_id: str | None = None
    run_id: str | None = None
    model: str | None = None
    estimated_input_tokens: int
    actual_usage: dict[str, int] | None = None
    duration_ms: float | None = None
    ttft_ms: float | None = None
    transformation: dict[str, Any] | None = None
    composition: dict[str, int] = Field(default_factory=dict)
    estimated_tokens_by_kind: dict[str, int] = Field(default_factory=dict)
    component_count: int | None = None
    component_counts: dict[str, int] = Field(default_factory=dict)
    components_truncated: bool = False
    omitted_component_count: int = 0
    metadata_truncated: bool = False
    components: list[dict[str, Any]] = Field(default_factory=list)


class RequestSnapshotHistoryOut(BaseModel):
    requests: list[RequestSnapshotOut]
    has_more: bool
    next_before: int | None = None


@router.get(
    "/agents/{agent_id}/threads/{thread_id}/requests",
    response_model=RequestSnapshotHistoryOut,
    summary="List persisted model requests",
)
async def list_requests(
    agent_id: str,
    thread_id: str,
    before: int | None = Query(None, ge=1),
    limit: int = Query(100, ge=1, le=200),
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    import asyncio

    return await asyncio.to_thread(
        RequestInspectionService(server.services.repos).list,
        int(user.id),
        agent_id,
        thread_id,
        before=before,
        limit=limit,
    )


@router.get(
    "/agents/{agent_id}/threads/{thread_id}/requests/{request_id}",
    response_model=RequestSnapshotOut,
    summary="Inspect final model request components",
    description="Returns retained text with truncation markers and content hashes. Media payloads and model transport credentials are omitted.",
)
async def get_request(
    agent_id: str,
    thread_id: str,
    request_id: str,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    import asyncio

    return await asyncio.to_thread(
        RequestInspectionService(server.services.repos).get,
        int(user.id),
        agent_id,
        thread_id,
        request_id,
    )
