"""HTTP adapter for independent work items (0043 / G3)."""

from __future__ import annotations

import asyncio
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from octop.api.common.agent import assert_agent_access
from octop.api.deps import (
    current_user,
    get_server,
    machine_principal_of,
    require_machine_scope,
)
from octop.infra.conversations.activity import record_task_activity
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


class PermissionBody(BaseModel):
    command_id: str = Field(
        min_length=1,
        max_length=128,
        description="Caller-generated idempotency key for this answer.",
    )
    pending_id: str = Field(
        min_length=1,
        max_length=128,
        description="The current permission_request.pending_id from task progress.",
    )
    attempt_id: str = Field(
        min_length=1,
        max_length=128,
        description="The task's current_attempt_id; stale answers are rejected.",
    )
    decisions: list[Literal["approve", "reject"]] = Field(min_length=1, max_length=100)


class InputReceipt(BaseModel):
    input_id: str
    task_id: str
    status: str


class InputReceiptLookup(BaseModel):
    receipt: InputReceipt | None


@router.post("/work-items", summary="Create an independent work item")
async def create_work_item(
    body: CreateBody,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    service: WorkItemsService = Depends(work_items_service),
) -> dict[str, Any]:
    if body.schema_version != WORK_ITEM_SCHEMA_VERSION:
        raise OctopError(ErrorCode.WORK_ITEM_INVALID, "unsupported schema_version")
    require_machine_scope(request, "tasks.create")
    principal = machine_principal_of(request)
    if principal is not None and not principal.allows_expert(body.agent_id.strip()):
        raise OctopError(ErrorCode.FORBIDDEN, "expert not in allowlist")
    if principal is not None:
        server.app_runtime.devices.agent_access_keys.require_task_target(
            target_kind=body.execution.target_kind,
            device_id=body.execution.device_id,
            working_dir=body.execution.working_dir,
            has_resources=bool(body.resources),
        )
        server.app_runtime.devices.agent_access_keys.require_thread(
            principal, body.agent_id.strip(), body.origin_thread_id.strip()
        )
    assert_agent_access(server, body.agent_id.strip(), user)
    created = await service.create(
        int(user.id), body, credential_id=principal.credential_id if principal else None
    )
    await asyncio.to_thread(
        record_task_activity,
        getattr(server.services, "repos", None),
        int(user.id),
        created["task_id"],
        body.command_id,
        "create",
    )
    if principal is not None:
        server.app_runtime.devices.agent_access_keys.grant_object(
            principal, "work_item", created["task_id"]
        )
        if created.get("worker_thread_id"):
            server.app_runtime.devices.agent_access_keys.grant_object(
                principal, "thread", created["worker_thread_id"]
            )
        if created.get("origin_thread_id"):
            server.app_runtime.devices.agent_access_keys.grant_object(
                principal, "thread", created["origin_thread_id"]
            )
    return created


@router.get("/work-items", summary="List work items for the current user")
async def list_work_items(
    request: Request,
    origin_thread_id: str | None = None,
    agent_id: str | None = None,
    status_group: Literal["open", "all"] = "open",
    limit: int = Query(default=50, ge=1, le=200),
    before: float | None = None,
    command_id: str | None = Query(default=None, min_length=1, max_length=128),
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    service: WorkItemsService = Depends(work_items_service),
) -> dict[str, Any]:
    require_machine_scope(request, "tasks.read")
    principal = machine_principal_of(request)
    payload = service.list_items(
        int(user.id),
        origin_thread_id=origin_thread_id,
        agent_id=agent_id,
        status_group=status_group,
        before=before,
        limit=limit,
        credential_id=principal.credential_id if principal else None,
        command_id=command_id,
    )
    if principal is not None:
        keys = server.app_runtime.devices.agent_access_keys
        items = [
            item
            for item in payload.get("items", [])
            if server.app_runtime.devices.agent_access_keys.owns_object(
                principal, "work_item", item["task_id"]
            )
        ]
        visible = []
        for item in items:
            try:
                keys.require_expert(principal, item["agent_id"])
            except OctopError:
                continue
            visible.append(item)
        payload = {**payload, "items": visible}
    return payload


@router.get("/work-items/{task_id}", summary="Work item detail")
async def get_work_item(
    task_id: str,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    service: WorkItemsService = Depends(work_items_service),
) -> dict[str, Any]:
    require_machine_scope(request, "tasks.read")
    principal = machine_principal_of(request)
    if principal is not None and not server.app_runtime.devices.agent_access_keys.owns_object(
        principal, "work_item", task_id
    ):
        raise OctopError(ErrorCode.FORBIDDEN, "work item not granted to this credential")
    return service.detail(int(user.id), task_id)


@router.get("/work-items/{task_id}/progress", summary="Read-only work item progress")
async def get_work_item_progress(
    task_id: str,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    service: WorkItemsService = Depends(work_items_service),
) -> dict[str, Any]:
    require_machine_scope(request, "tasks.read")
    principal = machine_principal_of(request)
    if principal is not None and not server.app_runtime.devices.agent_access_keys.owns_object(
        principal, "work_item", task_id
    ):
        raise OctopError(ErrorCode.FORBIDDEN, "work item not granted to this credential")
    return service.progress(int(user.id), task_id)


@router.get("/work-items/{task_id}/events", summary="Cursor events for a work item")
async def get_work_item_events(
    task_id: str,
    request: Request,
    before: int | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    service: WorkItemsService = Depends(work_items_service),
) -> dict[str, Any]:
    require_machine_scope(request, "tasks.read")
    principal = machine_principal_of(request)
    if principal is not None and not server.app_runtime.devices.agent_access_keys.owns_object(
        principal, "work_item", task_id
    ):
        raise OctopError(ErrorCode.FORBIDDEN, "work item not granted to this credential")
    return service.events(int(user.id), task_id, before=before, limit=limit)


@router.post("/work-items/{task_id}/inputs", summary="Append requirements to a work item")
async def post_work_item_input(
    task_id: str,
    body: InputBody,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    service: WorkItemsService = Depends(work_items_service),
) -> dict[str, Any]:
    if body.schema_version != WORK_ITEM_SCHEMA_VERSION:
        raise OctopError(ErrorCode.WORK_ITEM_INVALID, "unsupported schema_version")
    require_machine_scope(request, "tasks.input")
    principal = machine_principal_of(request)
    if principal is not None and not server.app_runtime.devices.agent_access_keys.owns_object(
        principal, "work_item", task_id
    ):
        raise OctopError(ErrorCode.FORBIDDEN, "work item not granted to this credential")
    result = await service.add_input(
        int(user.id),
        task_id,
        body,
        credential_id=principal.credential_id if principal else None,
    )
    await asyncio.to_thread(
        record_task_activity,
        getattr(server.services, "repos", None),
        int(user.id),
        task_id,
        body.command_id,
    )
    return result


@router.post("/work-items/{task_id}/cancel", summary="Request cancellation of a work item")
async def cancel_work_item(
    task_id: str,
    body: CancelBody,
    request: Request,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
    service: WorkItemsService = Depends(work_items_service),
) -> dict[str, Any]:
    require_machine_scope(request, "tasks.cancel")
    principal = machine_principal_of(request)
    if principal is not None and not server.app_runtime.devices.agent_access_keys.owns_object(
        principal, "work_item", task_id
    ):
        raise OctopError(ErrorCode.FORBIDDEN, "work item not granted to this credential")
    if body.schema_version != WORK_ITEM_SCHEMA_VERSION:
        raise OctopError(ErrorCode.WORK_ITEM_INVALID, "unsupported schema_version")
    return await service.cancel(int(user.id), task_id, body)


@router.get(
    "/work-items/{task_id}/inputs",
    summary="Find a previously submitted input receipt",
    response_model=InputReceiptLookup,
)
async def get_input_receipt(
    task_id: str,
    command_id: str = Query(min_length=1, max_length=128),
    user: Any = Depends(current_user),
    service: WorkItemsService = Depends(work_items_service),
) -> dict[str, Any]:
    return {"receipt": service.input_receipt(int(user.id), task_id, command_id)}


@router.post(
    "/work-items/{task_id}/permissions",
    summary="Answer a worker tool permission request",
    response_model=InputReceipt,
    description="Resumes only the current worker pause and attempt. Does not change tool policy or approve human task-board acceptance.",
)
async def answer_permission(
    task_id: str,
    body: PermissionBody,
    user: Any = Depends(current_user),
    service: WorkItemsService = Depends(work_items_service),
) -> dict[str, Any]:
    return await service.answer_permission(int(user.id), task_id, **body.model_dump())
