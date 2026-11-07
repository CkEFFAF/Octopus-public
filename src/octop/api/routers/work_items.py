"""HTTP adapter for independent work items (0043 / G3)."""

from __future__ import annotations

from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, Query

from octop.api.common.agent import assert_agent_access
from octop.api.deps import current_user, get_server
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.work_items.models import (
    WORK_ITEM_SCHEMA_VERSION,
    WorkItemCancel,
    WorkItemCreate,
    WorkItemInputCreate,
)
from octop.infra.work_items.service import WorkItemsService

router = APIRouter()


def work_items_service(server: Any = Depends(get_server)) -> WorkItemsService:
    assert server.app_runtime is not None
    service = getattr(server.app_runtime, "work_items", None)
    if service is None:
        raise OctopError(ErrorCode.INTERNAL_ERROR, "work items service unavailable")
    return cast(WorkItemsService, service)


class CreateBody(WorkItemCreate):
    pass


class InputBody(WorkItemInputCreate):
    pass


class CancelBody(WorkItemCancel):
    pass


@router.post("/work-items", summary="Create an independent work item")
async def create_work_item(
    body: CreateBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    service: WorkItemsService = Depends(work_items_service),
) -> dict[str, Any]:
    if body.schema_version != WORK_ITEM_SCHEMA_VERSION:
        raise OctopError(ErrorCode.WORK_ITEM_INVALID, "unsupported schema_version")
    assert_agent_access(server, body.agent_id.strip(), user)
    return await service.create(int(user.id), body)


@router.get("/work-items", summary="List work items for the current user")
async def list_work_items(
    origin_thread_id: str | None = None,
    status_group: Literal["open", "all"] = "open",
    limit: int = Query(default=50, ge=1, le=200),
    before: float | None = None,
    user: Any = Depends(current_user),
    service: WorkItemsService = Depends(work_items_service),
) -> dict[str, Any]:
    return service.list_items(
        int(user.id),
        origin_thread_id=origin_thread_id,
        status_group=status_group,
        before=before,
        limit=limit,
    )


@router.get("/work-items/{task_id}", summary="Work item detail")
async def get_work_item(
    task_id: str,
    user: Any = Depends(current_user),
    service: WorkItemsService = Depends(work_items_service),
) -> dict[str, Any]:
    return service.detail(int(user.id), task_id)


@router.get("/work-items/{task_id}/progress", summary="Read-only work item progress")
async def get_work_item_progress(
    task_id: str,
    user: Any = Depends(current_user),
    service: WorkItemsService = Depends(work_items_service),
) -> dict[str, Any]:
    return service.progress(int(user.id), task_id)


@router.get("/work-items/{task_id}/events", summary="Cursor events for a work item")
async def get_work_item_events(
    task_id: str,
    before: int | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    user: Any = Depends(current_user),
    service: WorkItemsService = Depends(work_items_service),
) -> dict[str, Any]:
    return service.events(int(user.id), task_id, before=before, limit=limit)


@router.post("/work-items/{task_id}/inputs", summary="Append requirements to a work item")
async def post_work_item_input(
    task_id: str,
    body: InputBody,
    user: Any = Depends(current_user),
    service: WorkItemsService = Depends(work_items_service),
) -> dict[str, Any]:
    if body.schema_version != WORK_ITEM_SCHEMA_VERSION:
        raise OctopError(ErrorCode.WORK_ITEM_INVALID, "unsupported schema_version")
    return await service.add_input(int(user.id), task_id, body)


@router.post("/work-items/{task_id}/cancel", summary="Request cancellation of a work item")
async def cancel_work_item(
    task_id: str,
    body: CancelBody,
    user: Any = Depends(current_user),
    service: WorkItemsService = Depends(work_items_service),
) -> dict[str, Any]:
    if body.schema_version != WORK_ITEM_SCHEMA_VERSION:
        raise OctopError(ErrorCode.WORK_ITEM_INVALID, "unsupported schema_version")
    return await service.cancel(int(user.id), task_id, body)
