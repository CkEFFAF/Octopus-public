"""Eight agent tools sharing the host mutation boundary; no human approval bypass."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from langgraph.config import get_config

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.task_board.models import BoardAction
from octop.infra.task_board.service import TaskBoardService


def build_task_board_tools(service: TaskBoardService) -> list[Any]:
    def user_id() -> int:
        config = get_config().get("configurable") or {}
        user = config.get("user")
        if user is None:
            raise ValueError("missing configurable.user")
        uid = int(user)
        if uid <= 0:
            raise ValueError("invalid configurable.user")
        return uid

    def result(value: object) -> str:
        return json.dumps(value, ensure_ascii=False)

    async def mutate(action: str, task_id: str, payload: dict[str, Any]) -> str:
        try:
            uid = user_id()
            board = service.snapshot(uid)
            command = BoardAction.model_validate(
                {
                    "action": action,
                    "task_id": task_id,
                    "payload": payload,
                    "revision": board.revision,
                }
            )
            return result((await service.action(uid, command, human=False)).model_dump())
        except OctopError as exc:
            return result(exc.to_envelope())
        except (ValueError, TypeError) as exc:
            return result({"error": str(exc)})

    async def task_board_list(project_id: str = "", tag: str = "", query: str = "") -> str:
        """List this user's visible tasks, optionally filtered by project, tag and text."""
        board = service.snapshot(user_id())
        return result(
            {
                "revision": board.revision,
                "tasks": [
                    task.model_dump()
                    for task in board.tasks
                    if not task.archived
                    and (not project_id or task.project_id == project_id)
                    and (not tag or tag in task.tags)
                    and (
                        not query
                        or query.casefold() in f"{task.title} {task.description}".casefold()
                    )
                ],
            }
        )

    async def task_board_get(task_id: str) -> str:
        """Get one task including dependencies, handover, run history and acceptance."""
        task = next(
            (task for task in service.snapshot(user_id()).tasks if task.id == task_id), None
        )
        if task is None:
            return result(OctopError(ErrorCode.NOT_FOUND, "task not found").to_envelope())
        return result(task.model_dump())

    async def task_board_create(
        title: str,
        description: str = "",
        prompt: str = "",
        project_id: str = "",
        agent_id: str = "",
        tags: list[str] | None = None,
        parent_id: str = "",
        device_id: str = "",
    ) -> str:
        """Create a draft task. A human must confirm the executor before it can run."""
        return await mutate(
            "create",
            "",
            {
                "title": title,
                "description": description,
                "prompt": prompt,
                "project_id": project_id,
                "agent_id": agent_id,
                "tags": tags or [],
                "parent_id": parent_id,
                "device_id": device_id,
            },
        )

    async def task_board_update(task_id: str, changes: dict[str, Any]) -> str:
        """Edit title, description, prompt, tags, goal, progress or next_step."""
        return await mutate("update", task_id, changes)

    async def task_board_manage(task_id: str, operation: str, status: str = "") -> str:
        """Archive, restore, cancel, or move a task. Completion still requires acceptance."""
        if operation not in {"archive", "restore", "cancel", "move"}:
            return result({"error": "unsupported operation"})
        return await mutate(operation, task_id, {"status": status} if status else {})

    async def task_board_run(task_id: str, request_id: str, cascade: bool = True) -> str:
        """Run a previously human-confirmed task; request_id deduplicates retries."""
        return await mutate("run", task_id, {"request_id": request_id, "cascade": cascade})

    async def task_board_set_parent(task_id: str, parent_id: str = "") -> str:
        """Set/remove a parent. Same project, no cycles, maximum depth three."""
        return await mutate("parent", task_id, {"parent_id": parent_id})

    async def task_board_schedule(
        task_id: str, cron: str, timezone: str, enabled: bool = True
    ) -> str:
        """Schedule a task using five-field cron and an IANA timezone. Confirmation is required to execute."""
        return await mutate(
            "schedule", task_id, {"cron": cron, "timezone": timezone, "enabled": enabled}
        )

    return [
        StructuredTool.from_function(coroutine=func)
        for func in (
            task_board_create,
            task_board_list,
            task_board_get,
            task_board_update,
            task_board_manage,
            task_board_run,
            task_board_set_parent,
            task_board_schedule,
        )
    ]
