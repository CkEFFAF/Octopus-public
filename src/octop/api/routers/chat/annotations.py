"""Versioned comment adapters and admission to the existing durable input queue."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from octop.api.deps import current_user, get_server
from octop.api.routers.chat.inputs import queue_input
from octop.api.routers.chat.models import QueuedInputBody, UserTurnWsFrame
from octop.infra.documents.annotations import Anchor, AnnotationService
from octop.infra.documents.file_sources import FileSourceService
from octop.infra.execution.service import ExecutionService

router = APIRouter()
BASE = "/agents/{agent_id}/threads/{thread_id}"


class AnnotationBody(BaseModel):
    version: str = Field(pattern="^[a-f0-9]{64}$")
    anchor: Anchor
    body: str = Field(min_length=1, max_length=8000)


class UpdateAnnotationBody(BaseModel):
    revision: int = Field(ge=1)
    body: str | None = Field(default=None, min_length=1, max_length=8000)
    status: Literal["open", "resolved"] | None = None
    reply: str | None = Field(default=None, min_length=1, max_length=8000)


class SelectedAnnotation(BaseModel):
    annotation_id: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=1)


class ModificationBody(BaseModel):
    command_id: str = Field(min_length=1, max_length=100, pattern="^[A-Za-z0-9_-]+$")
    resource_id: str = Field(min_length=1, max_length=100)
    source_version: str = Field(pattern="^[a-f0-9]{64}$")
    annotations: list[SelectedAnnotation] = Field(min_length=1, max_length=50)


@router.get(
    BASE + "/resources/{resource_id}/annotations",
    summary="List comments on an immutable file version",
)
async def list_annotations(
    agent_id: str,
    thread_id: str,
    resource_id: str,
    after: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    return AnnotationService(server.app_runtime.agent_registry).listing(
        int(user.id), agent_id, thread_id, resource_id, after, limit
    )


@router.post(
    BASE + "/resources/{resource_id}/annotations", summary="Save a typed file location comment"
)
async def create_annotation(
    agent_id: str,
    thread_id: str,
    resource_id: str,
    body: AnnotationBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    try:
        return AnnotationService(server.app_runtime.agent_registry).create(
            int(user.id), agent_id, thread_id, resource_id, body.version, body.anchor, body.body
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.patch(
    BASE + "/resources/{resource_id}/annotations/{annotation_id}",
    summary="Reply to or resolve a comment with revision protection",
)
async def update_annotation(
    agent_id: str,
    thread_id: str,
    resource_id: str,
    annotation_id: str,
    body: UpdateAnnotationBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    try:
        return AnnotationService(server.app_runtime.agent_registry).update(
            int(user.id),
            agent_id,
            thread_id,
            resource_id,
            annotation_id,
            body.revision,
            body.body,
            body.status,
            body.reply,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get(
    BASE + "/resources/{resource_id}/annotation-requests",
    summary="Inspect comment modification requests and linked output versions",
)
async def list_requests(
    agent_id: str,
    thread_id: str,
    resource_id: str,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    return {
        "items": AnnotationService(server.app_runtime.agent_registry).requests(
            int(user.id), agent_id, thread_id, resource_id
        )
    }


@router.post(
    BASE + "/annotation-requests", summary="Queue one version-bound comment modification request"
)
async def request_modification(
    agent_id: str,
    thread_id: str,
    body: ModificationBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    manager = server.app_runtime.agent_registry
    service = AnnotationService(manager)
    try:
        source = service.scope(int(user.id), agent_id, thread_id, body.resource_id)
        await FileSourceService(manager).assert_current(int(user.id), source)
        value = service.prepare_request(int(user.id), agent_id, thread_id, body.model_dump())
        if value["state"] != "pending":
            return value
        target = value["target"]
        settings: dict[str, Any] = {}
        if target["context_id"]:
            context = ExecutionService(manager._device_service).get(
                int(user.id), target["context_id"]
            )
            settings = {
                "target_kind": context.target_kind,
                "device_id": context.device_id,
                "working_dir": context.working_dir,
                "work_mode": context.work_mode,
            }
        queued = QueuedInputBody(
            command_id=body.command_id,
            turn=UserTurnWsFrame(thread_id=thread_id, text=value["text"], **settings),
            snapshot={
                "modification_request_id": value["request_id"],
                "resource_refs": [
                    {"resource_id": body.resource_id, "version": body.source_version}
                ],
                "annotations": value["annotations"],
            },
        )
        receipt = await queue_input(agent_id, thread_id, queued, user, server)
        return service.queued(int(user.id), value, receipt)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
