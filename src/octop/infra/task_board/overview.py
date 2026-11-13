"""A read-only projection of tasks, preserving each source's authority."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from octop.infra.db.repos.task_center import TaskCenterRepo
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.task_board.models import BoardSnapshot

Lifecycle = Literal["active", "completed", "failed", "inactive"]
Source = Literal["work_item", "board", "job", "subagent", "plan"]


class TaskOverviewItem(BaseModel):
    id: str
    source_id: str
    source: Source
    title: str
    status: str
    lifecycle: Lifecycle
    agent_id: str
    agent_name: str
    thread_id: str | None = None
    thread_title: str | None = None
    updated_at: float
    summary: str = ""
    stale: bool = False
    declared: bool = False


class TaskFilterOption(BaseModel):
    value: str
    label: str
    agent_id: str = ""


class TaskOverviewPage(BaseModel):
    items: list[TaskOverviewItem]
    total: int
    counts: dict[str, int]
    offset: int
    limit: int
    has_more: bool
    agents: list[TaskFilterOption]
    threads: list[TaskFilterOption]
    observed_at: float


def lifecycle(status: str, *, stale: bool = False) -> Lifecycle:
    if stale or status in {"cancelled", "unknown", "interrupted", "archived"}:
        return "inactive"
    if status in {"done", "completed", "succeeded"}:
        return "completed"
    if status == "failed":
        return "failed"
    return "active"


class TaskOverviewService:
    def __init__(self, manager: Any) -> None:
        self.manager = manager
        self.repos: RepoBundle = manager._repos
        self.repo = TaskCenterRepo(self.repos.db)

    def require_scope(self, owner: int, agent: str, thread: str) -> None:
        user = self.repos.user_repo.get(owner)
        conversation = self.repos.thread_repo.get(thread)
        if (
            user is None
            or user.disabled
            or conversation is None
            or (conversation.user_id, conversation.agent_id) != (owner, agent)
        ):
            raise OctopError.localized(ErrorCode.FORBIDDEN)

    def page(
        self,
        owner: int,
        *,
        agent: str = "",
        thread: str = "",
        state: str = "all",
        query: str = "",
        offset: int = 0,
        limit: int = 50,
        exclude_thread: str = "",
        include_board: bool = True,
    ) -> TaskOverviewPage:
        now = time.time()
        records = self.repo.records(owner, agent, thread, archived=state == "archived")
        items: list[TaskOverviewItem] = []
        for source, rows in records.items():
            for row in rows:
                if source == "plan":
                    plan = json.loads(row["payload_json"])
                    for task in plan.get("tasks", []):
                        items.append(
                            self._item(
                                row,
                                "plan",
                                source_id=f"{row['source_id']}:{task['task_id']}",
                                title=task["title"],
                                status=task["status"],
                                summary=task.get("reason", ""),
                                declared=True,
                            )
                        )
                elif source == "receipt":
                    payload = json.loads(row["payload_json"])
                    live = (
                        self.manager.steering_status(row["agent_id"], row["thread_id"])
                        if row["agent_id"] and row["thread_id"]
                        else None
                    ) or {}
                    stale = row["status"] in {"running", "started", "accepted", "waiting"} and (
                        payload.get("observation", {}).get("status") == "unavailable"
                        or (
                            now - row["updated_at"] > 45
                            and (row["kind"] == "job" or row["run_id"] != live.get("run_id"))
                        )
                    )
                    items.append(
                        self._item(
                            row,
                            "job" if row["kind"] == "job" else "subagent",
                            title=str(
                                payload.get("title")
                                or payload.get("subagent_type")
                                or payload.get("program")
                                or payload.get("name")
                                or row["source_id"]
                            ),
                            stale=stale,
                        )
                    )
                else:
                    items.append(self._item(row, "work_item"))

        revision, payload = (
            self.repos.task_board_repo.get(owner) if include_board else (0, '{"tasks":[]}')
        )
        board = BoardSnapshot.model_validate_json(
            json.dumps({"revision": revision, "timezone": "UTC", **json.loads(payload)})
        )
        board_threads = self.repos.thread_repo.get_many(
            [run.thread_id for task in board.tasks for run in task.runs if run.thread_id]
        )
        threads = {t.thread_id: t for t in board_threads if t.user_id == owner}
        for task in board.tasks:
            if task.archived != (state == "archived") or (agent and task.agent_id != agent):
                continue
            origin = next((r.thread_id for r in reversed(task.runs) if r.thread_id), None)
            if thread and origin != thread:
                continue
            expert = self.repos.agent_repo.get(task.agent_id) if task.agent_id else None
            conversation = threads.get(origin or "")
            items.append(
                TaskOverviewItem(
                    id=f"board:{task.id}",
                    source_id=task.id,
                    source="board",
                    title=task.title,
                    status=task.status,
                    lifecycle=lifecycle(task.status),
                    agent_id=task.agent_id,
                    agent_name=expert.name if expert else task.agent_id,
                    thread_id=origin,
                    thread_title=conversation.title if conversation else None,
                    updated_at=datetime.fromisoformat(task.updated_at).timestamp(),
                    summary=(task.progress or task.description)[:1000],
                )
            )
        if exclude_thread:
            items = [item for item in items if item.thread_id != exclude_thread]
        agents = {item.agent_id: item.agent_name for item in items if item.agent_id}
        thread_options = [
            TaskFilterOption(
                value=r["thread_id"], label=r["title"] or r["thread_id"], agent_id=r["agent_id"]
            )
            for r in self.repo.threads(owner, agent)
        ]
        if query.strip():
            needle = query.strip().casefold()
            items = [
                item
                for item in items
                if needle
                in f"{item.title} {item.summary} {item.agent_name} {item.thread_title or ''}".casefold()
            ]
        counts = {
            key: sum(item.lifecycle == key for item in items)
            for key in ("active", "completed", "failed", "inactive")
        }
        counts["all"] = len(items)
        if state not in {"all", "archived"}:
            items = [item for item in items if item.lifecycle == state]
        items.sort(key=lambda item: (item.updated_at, item.id), reverse=True)
        return TaskOverviewPage(
            items=items[offset : offset + limit],
            total=len(items),
            counts=counts,
            offset=offset,
            limit=limit,
            has_more=offset + limit < len(items),
            agents=[TaskFilterOption(value=k, label=v) for k, v in sorted(agents.items())],
            threads=thread_options,
            observed_at=now,
        )

    @staticmethod
    def _item(row: dict[str, Any], source: Source, **changes: Any) -> TaskOverviewItem:
        value = {
            **row,
            "source": source,
            "agent_name": row["agent_name"] or row["agent_id"] or "",
            "agent_id": row["agent_id"] or "",
            "status": row.get("status", "pending"),
            **changes,
        }
        return TaskOverviewItem(
            **{
                **value,
                "id": f"{source}:{value['source_id']}",
                "lifecycle": lifecycle(value["status"], stale=bool(value.get("stale"))),
            }
        )

    def record_todos(self, owner: int, agent: str, thread: str, run: str, raw: Any) -> None:
        self.require_scope(owner, agent, thread)
        if not run or not isinstance(raw, list):
            return
        tasks = []
        for index, todo in enumerate(raw[:64]):
            if not isinstance(todo, dict):
                continue
            title = str(todo.get("content") or todo.get("title") or "").strip()
            if not title:
                continue
            status = str(todo.get("status") or "pending")
            tasks.append(
                {
                    "task_id": str(index + 1),
                    "title": title[:500],
                    "status": {"in_progress": "running", "done": "completed"}.get(status, status),
                    "depends_on": [],
                    "reason": "",
                }
            )
        identity = (
            "plan_todos_"
            + hashlib.sha256(f"{owner}:{agent}:{thread}:{run}".encode()).hexdigest()[:32]
        )
        previous = self.repos.workbench_repo.get(owner, identity)
        revision = int(previous.get("revision", 0)) if previous else 0
        self.repos.workbench_repo.save(
            owner,
            agent,
            thread,
            "plan",
            identity,
            {
                "record_id": identity,
                "plan_id": "native-todos",
                "source": "write_todos",
                "run_id": run,
                "revision": revision + 1,
                "tasks": tasks,
                "updated_at": time.time(),
            },
            expected=revision,
        )
