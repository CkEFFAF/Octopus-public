"""Authenticated HTTP adapter for the host task ledger."""

from __future__ import annotations

import asyncio
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, ValidationError

from octop.api.deps import current_user, get_server
from octop.infra.task_board.models import BoardAction, BoardSnapshot, TaskDraft
from octop.infra.task_board.overview import TaskOverviewPage, TaskOverviewService
from octop.infra.task_board.service import TaskBoardService, invalid

router = APIRouter()


@router.get(
    "/task-center",
    response_model=TaskOverviewPage,
    summary="Browse tasks across experts and conversations",
    description="Account-scoped read-only task summaries. Reading never starts or steers a worker. "
    "Old terminal records are loaded only with lifecycle=archived.",
)
async def task_center(
    agent_id: str = "",
    thread_id: str = "",
    include_board: bool = True,
    lifecycle: Literal["active", "completed", "failed", "inactive", "all", "archived"] = "active",
    query: str = Query("", max_length=500),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> TaskOverviewPage:
    service = TaskOverviewService(server.app_runtime.agent_registry)
    return await asyncio.to_thread(
        service.page,
        int(user.id),
        agent=agent_id,
        thread=thread_id,
        state=lifecycle,
        query=query,
        offset=offset,
        limit=limit,
        include_board=include_board,
    )


def board_service(server: Any = Depends(get_server)) -> TaskBoardService:
    assert server.app_runtime is not None and server.app_runtime.task_board is not None
    return cast(TaskBoardService, server.app_runtime.task_board)


class ParseBody(BaseModel):
    agent_id: str
    text: str = Field(min_length=1, max_length=20000)
    model: str = ""


@router.get("/task-board", response_model=BoardSnapshot, summary="Read the user's task ledger")
async def get_board(
    user: Any = Depends(current_user),
    service: TaskBoardService = Depends(board_service),
) -> BoardSnapshot:
    return service.snapshot(int(user.id))


@router.post(
    "/task-board/actions",
    response_model=BoardSnapshot,
    summary="Mutate a task with revision checking",
)
async def act(
    command: BoardAction,
    user: Any = Depends(current_user),
    service: TaskBoardService = Depends(board_service),
) -> BoardSnapshot:
    try:
        return await service.action(int(user.id), command)
    except (ValidationError, ValueError, TypeError) as exc:
        raise invalid("invalid task fields") from exc


@router.post(
    "/task-board/parse",
    response_model=TaskDraft,
    summary="Use the configured model to draft a task",
)
async def parse(
    body: ParseBody,
    user: Any = Depends(current_user),
    service: TaskBoardService = Depends(board_service),
) -> TaskDraft:
    return await service.parse(int(user.id), body.agent_id, body.text, body.model)
