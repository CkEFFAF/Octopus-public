"""One mutation boundary for the dashboard, agent tools and host scheduler."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from octop.infra.agents.manager import AgentManager
from octop.infra.cron.delivery import CronDeliveryCommand, CronDeliveryService
from octop.infra.cron.trigger import build_trigger
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.gateway.gateway import Gateway
from octop.infra.task_board.acceptance import judge
from octop.infra.task_board.models import (
    BoardAction,
    BoardSnapshot,
    BoardTask,
    Handover,
    Review,
    Run,
    Schedule,
    TaskDraft,
)
from octop.infra.utils.llm_text import ainvoke_text
from octop.infra.utils.ulid import new_ulid


def invalid(reason: str) -> OctopError:
    return OctopError(ErrorCode.TASK_BOARD_INVALID, reason, details={"reason": reason})


def next_fire(schedule: Schedule, now: datetime) -> str:
    if len(schedule.cron.split()) != 5:
        raise invalid("cron requires five fields")
    try:
        ZoneInfo(schedule.timezone)
        fields = schedule.cron.split()
        expressions = [fields]
        # Vixie cron: restricted day-of-month and weekday are alternatives.
        if not fields[2].startswith("*") and not fields[4].startswith("*"):
            expressions = [[*fields[:4], "*"], [*fields[:2], "*", *fields[3:]]]
        candidates = []
        for expression in expressions:
            trigger = build_trigger(f"cron:{' '.join(expression)}", timezone=schedule.timezone)
            assert isinstance(trigger, CronTrigger)
            candidate = trigger.get_next_fire_time(None, now + timedelta(seconds=1))
            if candidate:
                candidates.append(candidate)
        following = min(candidates) if candidates else None
    except (ValueError, KeyError, OctopError) as exc:
        raise invalid("invalid cron or IANA timezone") from exc
    if following is None:
        raise invalid("cron has no future occurrence")
    return str(following.isoformat())


class TaskBoardService:
    def __init__(
        self,
        *,
        repos: RepoBundle,
        timezone: str,
        registry: AgentManager,
        gateway: Gateway,
        delivery: CronDeliveryService,
    ) -> None:
        self._repos = repos
        self.timezone = timezone
        self._registry = registry
        self._gateway = gateway
        self._delivery = delivery
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self._devices: Any | None = None
        self._peers: Any | None = None

    def set_device_service(self, service: Any) -> None:
        self._devices = service

    def set_peer_service(self, service: Any) -> None:
        self._peers = service

    async def _wait_for_operations(self, owner: int, run_id: str) -> None:
        if self._peers is not None:
            await self._peers.wait_for_task_run(owner, run_id)
        if self._devices is not None:
            await self._devices.wait_for_task_run(owner, run_id)

    def _device_evidence(self, owner: int, run_id: str, output: str) -> str:
        if self._devices is None:
            return output
        operations = self._repos.device_repo.list_for_task_run(owner, run_id)
        if not operations:
            return output
        evidence = [
            {
                "operation_id": op.operation_id,
                "device_id": op.device_id,
                "action": op.action,
                "status": op.status,
                "result": op.result,
                "error": op.error,
            }
            for op in operations
        ]
        return f"{output}\n\nDevice execution evidence:\n{json.dumps(evidence, ensure_ascii=False)[:20000]}"

    async def _cancel_operations(self, owner: int, run_id: str) -> None:
        if self._peers is not None:
            await self._peers.cancel_task_run(owner, run_id)
        if self._devices is not None:
            await self._devices.cancel_task_run(owner, run_id)

    def replace_repos(self, repos: RepoBundle) -> None:
        self._repos = repos
        self._delivery.replace_repos(repos)

    def _now(self) -> datetime:
        return datetime.now(ZoneInfo(self.timezone))

    def snapshot(self, user_id: int) -> BoardSnapshot:
        revision, payload = self._repos.task_board_repo.get(user_id)
        parsed = json.loads(payload)
        return BoardSnapshot(
            revision=revision,
            timezone=self.timezone,
            tasks=[BoardTask.model_validate(task) for task in parsed["tasks"]],
            tag_prefixes=parsed.get("tag_prefixes", {}),
        )

    def _save(self, user_id: int, board: BoardSnapshot) -> BoardSnapshot:
        payload = json.dumps(
            {
                "tasks": [task.model_dump() for task in board.tasks],
                "tag_prefixes": board.tag_prefixes,
            },
            ensure_ascii=False,
        )
        if not self._repos.task_board_repo.save(user_id, board.revision, payload):
            raise OctopError(ErrorCode.TASK_BOARD_CONFLICT, "task board revision changed")
        board.revision += 1
        return board

    def _agent_pin(self, user_id: int, agent_id: str) -> str:
        row = self._repos.agent_repo.get(agent_id)
        # Running a shared expert would grant another owner's tools to this ledger.
        if row is None or row.user_id != user_id:
            raise OctopError(ErrorCode.FORBIDDEN, "task executor must be owned by user")
        profile = [
            row.agent_id,
            row.config_json,
            row.default_model,
            row.system_prompt,
            row.mcp_servers,
            row.knowledge_base_ids,
            row.skill_package_ids,
            self._repos.settings_repo.get("security_policy"),
            self._repos.settings_repo.get_active_model(user_id),
        ]
        return hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()

    def _project(self, user_id: int, task: BoardTask) -> None:
        if not task.project_id:
            return
        from octop.infra.agents.teams.service import TeamService

        row = self._repos.agent_repo.get(task.project_id)
        if row is None or row.user_id != user_id or row.kind != "team":
            raise OctopError(ErrorCode.FORBIDDEN, "project room must be owned by user")
        members = TeamService(
            self._repos, workspace_for=self._registry.workspace_for_agent
        ).visible_member_ids(task.project_id)
        if task.agent_id and task.agent_id not in [task.project_id, *members]:
            raise invalid("executor is not a member of this project")

    def _task_pin(self, user_id: int, task: BoardTask) -> str:
        pin = self._agent_pin(user_id, task.agent_id)
        if not task.device_id:
            return pin
        if self._devices is None:
            raise invalid("device service unavailable")
        device = self._devices.owned(user_id, task.device_id)
        return hashlib.sha256(f"{pin}:{task.device_id}:{device.grant_version}".encode()).hexdigest()

    @staticmethod
    def _find(board: BoardSnapshot, task_id: str) -> BoardTask:
        for task in board.tasks:
            if task.id == task_id:
                return task
        raise OctopError(ErrorCode.NOT_FOUND, "task not found")

    @staticmethod
    def _busy(task: BoardTask) -> bool:
        return bool(task.runs and task.runs[-1].state == "running")

    def _parent(self, board: BoardSnapshot, task: BoardTask, *, changing: bool) -> None:
        # Validate the whole graph, including descendants when reparenting a subtree.
        for item in board.tasks:
            seen = {item.id}
            cursor = item
            depth = 0
            while cursor.parent_id:
                parent = self._find(board, cursor.parent_id)
                if parent.id in seen or parent.project_id != item.project_id:
                    raise invalid("parent cycle or different project")
                seen.add(parent.id)
                depth += 1
                if depth > 3:
                    raise invalid("maximum parent depth is three")
                cursor = parent
        if changing and task.parent_id:
            parent = self._find(board, task.parent_id)
            if parent.archived:
                raise invalid("cannot add children to an archived parent")
            if self._busy(parent):
                raise invalid("cannot change children of an executing parent")

    @staticmethod
    def _contract(task: BoardTask) -> str:
        fields = [
            task.title,
            task.description,
            task.prompt,
            task.goal,
            task.agent_id,
            task.model,
            task.reviewer_model,
            task.acceptance,
            task.tags,
            task.tag_prompt,
        ]
        # Preserve accepted contracts for existing tasks without a remote target.
        if task.device_id:
            fields.append(task.device_id)
        return hashlib.sha256(json.dumps(fields).encode()).hexdigest()

    @staticmethod
    def _accepted(task: BoardTask) -> bool:
        return bool(
            task.runs
            and task.runs[-1].state == "succeeded"
            and task.review
            and task.review.passed
            and task.review.run_id == task.runs[-1].id
            and task.runs[-1].contract == TaskBoardService._contract(task)
        )

    def _settle(self, board: BoardSnapshot) -> None:
        # Bottom-up completion. Archived children still count toward the contract.
        for _ in range(4):
            for task in board.tasks:
                children = [child for child in board.tasks if child.parent_id == task.id]
                complete = self._accepted(task) and all(
                    child.status == "done" for child in children
                )
                if complete and not self._busy(task):
                    task.status = "done"
                elif task.status == "done":
                    task.status = "running" if self._accepted(task) else "todo"
                elif (
                    children
                    and self._accepted(task)
                    and any(child.status == "failed" for child in children)
                ):
                    task.status = "failed"

    def _tree(self, board: BoardSnapshot, task: BoardTask) -> list[BoardTask]:
        result = [task]
        for child in board.tasks:
            if child.parent_id == task.id:
                result.extend(self._tree(board, child))
        return result

    def _ready(self, user_id: int, task: BoardTask) -> None:
        if task.archived or self._busy(task):
            raise invalid("task tree contains archived or executing tasks")
        self._project(user_id, task)
        if not task.pin or task.pin != self._task_pin(user_id, task):
            raise OctopError(ErrorCode.TASK_BOARD_PIN_REQUIRED, "confirm the current agent profile")
        harness = self._registry.get_agent(task.agent_id)
        for ref in (task.model, task.reviewer_model):
            if ref:
                harness.model_factory.get(ref)

    async def action(
        self,
        user_id: int,
        command: BoardAction,
        *,
        human: bool = True,
    ) -> BoardSnapshot:
        board = self.snapshot(user_id)
        if command.revision != board.revision:
            raise OctopError(ErrorCode.TASK_BOARD_CONFLICT, "task board revision changed")
        now = self._now().isoformat()
        payload: dict[str, Any] = command.payload
        if command.action == "tags":
            old = str(payload.get("name", "")).strip()
            renamed = str(payload.get("rename", old)).strip()
            if not old or len(old) > 60 or len(renamed) > 60:
                raise invalid("invalid tag name")
            affected = [
                item
                for item in board.tasks
                if old in item.tags or (renamed and renamed in item.tags)
            ]
            if any(self._busy(item) for item in affected):
                raise invalid("cancel tagged executions before changing tags")
            for item in affected:
                item.tags = list(
                    dict.fromkeys(
                        renamed if tag == old else tag for tag in item.tags if tag != old or renamed
                    )
                )
                item.updated_at = now
            prefix = str(payload.get("prefix", board.tag_prefixes.get(old, "")))
            if len(prefix) > 10000:
                raise invalid("tag prompt prefix too long")
            board.tag_prefixes.pop(old, None)
            if renamed and prefix:
                board.tag_prefixes[renamed] = prefix
            # Prompt changes must be re-confirmed, including archived cards.
            for item in affected:
                item.pin = ""
                item.review = None
                item.tag_prompt = ""
            self._settle(board)
            return self._save(user_id, board)
        launches: list[tuple[BoardTask, Run]] = []
        task = None if command.action == "create" else self._find(board, command.task_id)
        if task and task.archived and command.action != "restore":
            raise invalid("archived tasks are read only")
        if (
            task
            and command.action == "run"
            and any(run.request_id == payload.get("request_id") for run in task.runs)
        ):
            return board
        if task and self._busy(task) and command.action != "cancel":
            raise invalid("cancel the active run before editing")
        if command.action == "create":
            if len(board.tasks) >= 2000:
                raise invalid("task limit reached")
            draft = TaskDraft.model_validate(payload)
            task = BoardTask(**draft.model_dump(), id=new_ulid(), created_at=now, updated_at=now)
            task.title = task.title.strip()
            task.goal = task.description or task.title
            board.tasks.append(task)
        assert task is not None
        if command.action == "update":
            allowed = {
                "title",
                "description",
                "prompt",
                "tags",
                "progress",
                "next_step",
                "goal",
                "model",
                "reviewer_model",
                "acceptance",
                "auto_repair",
                "continue_session",
                "device_id",
            }
            if set(payload) - allowed:
                raise invalid("use handover to change executor and parent to change dependencies")
            changed = BoardTask.model_validate({**task.model_dump(), **payload})
            # Changing the task contract invalidates previous acceptance.
            if any(
                getattr(task, key) != getattr(changed, key)
                for key in (
                    "title",
                    "description",
                    "prompt",
                    "goal",
                    "model",
                    "reviewer_model",
                    "acceptance",
                    "auto_repair",
                    "continue_session",
                    "device_id",
                    "tags",
                )
            ):
                changed.review = None
                changed.pin = ""
                changed.tag_prompt = ""
            board.tasks[board.tasks.index(task)] = task = changed
        elif command.action == "parent":
            task.parent_id = str(payload.get("parent_id", ""))
        elif command.action == "handover":
            target = str(payload.get("agent_id", ""))
            self._agent_pin(user_id, target)
            handover = Handover(
                goal=str(payload.get("goal") or task.goal or task.title),
                progress=str(payload.get("progress") or task.progress),
                next_step=str(payload.get("next_step") or task.next_step),
                from_agent=task.agent_id,
                to_agent=target,
                created_at=now,
            )
            task.handovers = [*task.handovers, handover][-20:]
            task.agent_id = target
            task.pin = ""
            task.review = None
            task.status = "todo"
            task.goal, task.progress, task.next_step = (
                handover.goal,
                handover.progress,
                handover.next_step,
            )
        elif command.action == "confirm":
            if not human:
                raise OctopError(
                    ErrorCode.FORBIDDEN, "only a human can confirm execution configuration"
                )
            for item in self._tree(board, task) if payload.get("cascade") else [task]:
                if item.archived or self._busy(item):
                    raise invalid("task tree contains archived or executing tasks")
                self._project(user_id, item)
                item.pin = self._task_pin(user_id, item)
                item.tag_prompt = "\n\n".join(
                    board.tag_prefixes[tag] for tag in item.tags if board.tag_prefixes.get(tag)
                )
            if task.status == "planning":
                task.status = "todo"
        elif command.action in ("archive", "restore"):
            task.archived = command.action == "archive"
            if task.archived and task.schedule:
                task.schedule.enabled = False
        elif command.action == "move":
            status = str(payload.get("status", ""))
            if status == "done" and not self._accepted(task):
                raise invalid("an independently accepted run is required")
            if status not in ("planning", "todo", "done", "failed"):
                raise invalid("running status is controlled by the host")
            task.status = status  # type: ignore[assignment]
        elif command.action == "schedule":
            task.schedule = Schedule.model_validate(payload) if payload else None
            if task.schedule:
                task.schedule.next_run = next_fire(task.schedule, self._now())
        elif command.action == "review":
            if not human:
                raise OctopError(ErrorCode.FORBIDDEN, "agent tools cannot submit human acceptance")
            if not task.runs or task.runs[-1].state != "succeeded":
                raise invalid("a successful execution is required before acceptance")
            if task.runs[-1].contract != self._contract(task):
                raise invalid("task contract changed; execute again before acceptance")
            scores = [float(value) for value in payload.get("scores", [])]
            if len(scores) != 3 or not all(0 <= value <= 100 for value in scores):
                raise invalid("three finite scores from 0 to 100 are required")
            task.review = Review(
                reviewer=f"user:{user_id}",
                scores=scores,
                evidence=str(payload.get("evidence", "")).strip(),
                passed=all(value >= 65 for value in scores),
                created_at=now,
                run_id=task.runs[-1].id,
            )
            task.runs[-1].review = task.review.model_copy(deep=True)
            task.status = "running" if task.review.passed else "failed"
        elif command.action == "run":
            pending = (
                [
                    item
                    for item in self._tree(board, task)
                    if item.id == task.id or item.status != "done"
                ]
                if payload.get("cascade")
                else [task]
            )
            if len(self._jobs) + len(pending) > 8:
                raise invalid("host execution limit reached")
            request_id = str(payload.get("request_id") or new_ulid())
            if any(run.request_id == request_id for run in task.runs):
                return board
            for item in pending:
                self._ready(user_id, item)
            for item in pending:
                run = Run(
                    id=new_ulid(),
                    request_id=request_id if item.id == task.id else f"{request_id}:{item.id}",
                    contract=self._contract(item),
                    agent_id=item.agent_id,
                    started_at=now,
                )
                item.runs = [*item.runs, run][-20:]
                item.review = None
                item.status = "running"
                item.updated_at = now
                launches.append((item, run))
        elif command.action == "verify":
            if not human:
                raise OctopError(ErrorCode.FORBIDDEN, "only a human can retry acceptance anomalies")
            if (
                task.acceptance != "automatic"
                or not task.runs
                or task.runs[-1].state != "succeeded"
            ):
                raise invalid("a successful automatic execution is required")
            run = task.runs[-1]
            if run.contract != self._contract(task) or not run.thread_id:
                raise invalid("task contract changed; execute again")
            if len(self._jobs) >= 8:
                raise invalid("host execution limit reached")
            self._ready(user_id, task)
            run.state, run.phase, run.acceptance_error = "running", "reviewing", ""
            task.review = None
            task.status = "running"
            launches.append((task, run))
        elif command.action == "cancel":
            if not any(
                self._busy(item)
                for item in (self._tree(board, task) if payload.get("cascade") else [task])
            ):
                raise invalid("no active run")
            cancelled_runs: list[tuple[str, str]] = []
            cancelled_jobs: list[asyncio.Task[None]] = []
            for item in self._tree(board, task) if payload.get("cascade") else [task]:
                if not self._busy(item):
                    continue
                job = self._jobs.get(item.runs[-1].id)
                cancelled_runs.append((item.id, item.runs[-1].id))
                if job:
                    job.cancel()
                    cancelled_jobs.append(job)
            # Let runtime cancellation record its result before merging this action.
            await asyncio.gather(*cancelled_jobs, return_exceptions=True)
            for _, run_id in cancelled_runs:
                await self._cancel_operations(user_id, run_id)
            board = self.snapshot(user_id)
            task = self._find(board, command.task_id)
            for task_id, run_id in cancelled_runs:
                item = self._find(board, task_id)
                run = next(run for run in item.runs if run.id == run_id)
                if run.state == "running":
                    run.state = "interrupted"
                    run.ended_at = now
                if item.runs[-1].id == run_id:
                    item.status = "failed"
        task.tags = list(dict.fromkeys(tag.strip() for tag in task.tags if tag.strip()))
        if any(len(tag) > 60 for tag in task.tags) or not task.title.strip():
            raise invalid("invalid title or tag")
        if command.action in {"create", "handover", "confirm", "run"}:
            self._project(user_id, task)
            if task.agent_id:
                self._agent_pin(user_id, task.agent_id)
        self._parent(board, task, changing=command.action in {"create", "parent"})
        task.updated_at = now
        self._settle(board)
        if command.action == "move" and payload.get("status") == "done" and task.status != "done":
            raise invalid("all child tasks must be completed")
        result = self._save(user_id, board)
        for item, run in launches:
            self._jobs[run.id] = asyncio.create_task(
                self._execute(user_id, item, run, review_only=command.action == "verify"),
                name=f"board:{run.id}",
            )
        return result

    def _record(self, user_id: int, task_id: str, run_id: str, **changes: Any) -> None:
        board = self.snapshot(user_id)
        task = self._find(board, task_id)
        run = next((item for item in task.runs if item.id == run_id), None)
        if run is None or run.state != "running":
            return
        for key, value in changes.items():
            setattr(run, key, value)
        if run.state != "running":
            task.status = "running" if run.state == "succeeded" else "failed"
            task.progress = run.output[:1000] or run.error
            task.review = run.review
        task.updated_at = self._now().isoformat()
        self._settle(board)
        self._save(user_id, board)

    async def _execute(
        self, user_id: int, task: BoardTask, run: Run, *, review_only: bool = False
    ) -> None:
        try:
            # Recheck the immutable execution pin immediately before entering runtime.
            if task.pin != self._task_pin(user_id, task):
                raise invalid("executor configuration changed")
            session_key = f"{task.agent_id}:dashboard:{user_id}:board-{'task-' + task.id if task.continue_session else run.id}"
            thread_id = (
                run.thread_id
                if review_only
                else await self._gateway.thread_registry.get_or_create_by_key(
                    session_key=session_key,
                    agent_id=task.agent_id,
                    user_id=user_id,
                    channel_type="dashboard",
                    channel_metadata={"task_id": task.id},
                )
            )
            assert thread_id is not None
            self._record(user_id, task.id, run.id, thread_id=thread_id)
            prompt = task.prompt or task.description or task.title
            prompt = "\n\n".join(part for part in (task.tag_prompt, prompt) if part)
            if task.handovers:
                prompt += f"\n\nHandover:\nGoal: {task.goal}\nProgress: {task.progress}\nNext: {task.next_step}"
            command = CronDeliveryCommand(
                cron_id=task.id,
                cron_name=task.title,
                agent_id=task.agent_id,
                user_id=user_id,
                session_key=session_key,
                prompt=prompt,
                fresh_thread=False,
                task_type="agent",
                model=task.model or None,
                mcp_servers=(),
                device_id=task.device_id,
                task_run_id=run.id,
                device_grant_version=(
                    self._devices.owned(user_id, task.device_id).grant_version
                    if task.device_id and self._devices is not None
                    else 0
                ),
            )
            output = run.output if review_only else await self._delivery.deliver(command)
            if not review_only:
                await self._wait_for_operations(user_id, run.id)
                output = self._device_evidence(user_id, run.id, output)
            review = None
            attempts: list[Review] = []
            acceptance_error = ""
            if task.acceptance == "automatic":
                for attempt in range(2 if task.auto_repair else 1):
                    self._record(user_id, task.id, run.id, output=output[:30000], phase="reviewing")
                    try:
                        harness = self._registry.get_agent(task.agent_id)
                        model = task.reviewer_model or harness.config.pick_default_model_ref()
                        messages = await harness.aget_history(thread_id, limit=500)
                        evidence = json.dumps(
                            [
                                message.model_dump() if hasattr(message, "model_dump") else message
                                for message in messages
                            ],
                            ensure_ascii=False,
                            default=str,
                        )
                        run.output, run.thread_id = output[:30000], thread_id
                        review = await judge(
                            llm=harness.model_factory.get(model),
                            model=str(model),
                            task=task,
                            run=run,
                            evidence=evidence,
                            user_id=user_id,
                            repos=self._repos,
                            created_at=self._now().isoformat(),
                        )
                        attempts.append(review)
                        self._record(user_id, task.id, run.id, attempts=attempts)
                    except Exception as exc:
                        acceptance_error = str(exc)[:2000]
                        break  # An infrastructure anomaly is never a quality verdict.
                    if review.passed or attempt == 1 or not task.auto_repair:
                        break
                    self._record(user_id, task.id, run.id, phase="executing")
                    repair = command.__class__(
                        **{
                            **command.__dict__,
                            "prompt": f"Repair the deliverable for the original task. Do not change the task contract.\n{prompt}\nIndependent reviewer issues:\n{review.evidence}",
                        }
                    )
                    output = await self._delivery.deliver(repair)
                    await self._wait_for_operations(user_id, run.id)
                    output = self._device_evidence(user_id, run.id, output)
            self._record(
                user_id,
                task.id,
                run.id,
                state="succeeded",
                output=output[:30000],
                phase="finished",
                review=review,
                attempts=attempts,
                acceptance_error=acceptance_error,
                ended_at=self._now().isoformat(),
            )
            if task.acceptance == "automatic" and (
                review is None or not review.passed or acceptance_error
            ):
                board = self.snapshot(user_id)
                self._find(board, task.id).status = "running" if acceptance_error else "failed"
                self._settle(board)
                self._save(user_id, board)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await self._cancel_operations(user_id, run.id)
            self._record(
                user_id,
                task.id,
                run.id,
                state="interrupted",
                error="Host stopped or run cancelled",
                ended_at=self._now().isoformat(),
            )
        except Exception as exc:
            self._record(
                user_id,
                task.id,
                run.id,
                state="failed",
                error=str(exc)[:2000],
                ended_at=self._now().isoformat(),
            )
        finally:
            self._jobs.pop(run.id, None)

    def recover(self) -> None:
        for user_id in self._repos.task_board_repo.user_ids():
            board = self.snapshot(user_id)
            changed = False
            for task in board.tasks:
                if self._busy(task):
                    task.runs[-1].state = "interrupted"
                    task.runs[-1].error = "Host restarted; execution was not resent"
                    task.runs[-1].ended_at = self._now().isoformat()
                    task.status = "failed"
                    changed = True
                # Skip missed ticks after downtime, rather than executing a backlog.
                if (
                    task.schedule
                    and task.schedule.next_run
                    and datetime.fromisoformat(task.schedule.next_run) < self._now()
                ):
                    task.schedule.next_run = next_fire(task.schedule, self._now())
                    changed = True
            if changed:
                self._save(user_id, board)

    async def tick(self) -> None:
        for user_id in self._repos.task_board_repo.user_ids():
            board = self.snapshot(user_id)
            for task_id in [item.id for item in board.tasks]:
                board = self.snapshot(user_id)
                task = self._find(board, task_id)
                rule = task.schedule
                if not rule or not rule.enabled or task.archived or not rule.next_run:
                    continue
                if datetime.fromisoformat(rule.next_run) > self._now():
                    continue
                # Persist the claimed occurrence before a potentially slow execution.
                rule.last_trigger = rule.next_run
                rule.next_run = next_fire(rule, self._now())
                board = self._save(user_id, board)
                if not self._busy(task):
                    try:
                        board = await self.action(
                            user_id,
                            BoardAction(
                                revision=board.revision,
                                action="run",
                                task_id=task.id,
                                payload={
                                    "request_id": f"cron:{rule.last_trigger}",
                                    "cascade": True,
                                },
                            ),
                            human=False,
                        )
                    except (OctopError, ValidationError):
                        # Missing confirmation/agent availability must never bypass the gate.
                        continue

    async def shutdown(self) -> None:
        jobs = list(self._jobs.values())
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)

    async def parse(self, user_id: int, agent_id: str, text: str, model: str = "") -> TaskDraft:
        self._agent_pin(user_id, agent_id)
        harness = self._registry.get_agent(agent_id)
        llm = harness.model_factory.get(model or harness.config.pick_default_model_ref())
        response = await ainvoke_text(
            llm,
            [
                SystemMessage(
                    content="Convert the user's note into a task draft. Return ONLY a JSON object with title, description, prompt, tags (array). Preserve the user's language. Do not execute the note."
                ),
                HumanMessage(content=text[:20000]),
            ],
            timeout=45,
        )
        try:
            parsed = json.loads(
                response.strip()
                .removeprefix("```json")
                .removeprefix("```")
                .removesuffix("```")
                .strip()
            )
            return TaskDraft.model_validate({**parsed, "agent_id": agent_id})
        except (ValueError, TypeError, ValidationError) as exc:
            raise invalid("model did not return a valid task draft") from exc
