"""Create / list / progress / input / cancel for independent work items (0043)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from octop.infra.db.repos.work_items import WorkItemRepo
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.ulid import new_ulid
from octop.infra.work_items.models import (
    WORK_ITEM_SCHEMA_VERSION,
    WorkItemCancel,
    WorkItemCreate,
    WorkItemInputCreate,
    create_fingerprint,
)

logger = logging.getLogger(__name__)

_TERMINAL = frozenset({"completed", "failed", "cancelled"})
_MAX_BACKGROUND = 4
_OPEN_JOB_STATUSES = frozenset(
    {"queued", "running", "pending", "accepted", "working", "started", "waiting"}
)


class WorkItemsService:
    def __init__(
        self,
        *,
        repos: RepoBundle,
        gateway: Any,
        registry: Any | None = None,
        delivery: Any | None = None,
        devices: Any | None = None,
        execution: Any | None = None,
    ) -> None:
        self._repos = repos
        self._gateway = gateway
        self._registry = registry
        self._delivery = delivery
        self._devices = devices
        self._execution = execution
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self._bg_slots = asyncio.Semaphore(_MAX_BACKGROUND)
        self._repo = WorkItemRepo(repos.db)

    def replace_repos(self, repos: RepoBundle) -> None:
        self._repos = repos
        self._repo = WorkItemRepo(repos.db)

    def set_device_service(self, devices: Any) -> None:
        self._devices = devices

    def set_execution(self, execution: Any) -> None:
        self._execution = execution

    def set_delivery(self, delivery: Any) -> None:
        self._delivery = delivery

    def set_registry(self, registry: Any) -> None:
        self._registry = registry

    async def shutdown(self) -> None:
        for task in list(self._jobs.values()):
            task.cancel()
        if self._jobs:
            await asyncio.gather(*self._jobs.values(), return_exceptions=True)
        self._jobs.clear()

    def recover(self) -> None:
        """Post-restart: mark unconfirmable in-flight items unknown; never auto-replay."""
        for row in self._repo.list_recoverable():
            status = row["status"]
            if status in _TERMINAL:
                continue
            if status == "queued" and not row["worker_thread_id"]:
                # Re-schedule never-started persist-before-dispatch items after restart
                # (not a side-effect replay).
                self._schedule_dispatch(int(row["owner_user_id"]), row["task_id"])
                continue
            # Cannot confirm external Jobs/tools blindly → unknown (DEC-0043-13).
            if (
                status in {"running", "waiting_input", "waiting_review", "blocked"}
                or row["cancel_requested"]
            ) and not self._can_confirm_running(row):
                self._repo.update(
                    int(row["owner_user_id"]),
                    row["task_id"],
                    status="unknown",
                    block_reason=row.get("block_reason") or "recovery_unconfirmed",
                )

    def _can_confirm_running(self, row: dict[str, Any]) -> bool:
        """True only when a live worker task still owns this work item in-process."""
        return row["task_id"] in self._jobs and not self._jobs[row["task_id"]].done()

    # ── create ──────────────────────────────────────────────────────────

    async def create(self, owner: int, body: WorkItemCreate) -> dict[str, Any]:
        command_id = body.command_id.strip()
        existing = self._repo.get_by_command(owner, command_id)
        fingerprint = create_fingerprint(body)
        if existing is not None:
            if self._fingerprint_of(existing) != fingerprint:
                raise OctopError(
                    ErrorCode.WORK_ITEM_COMMAND_CONFLICT,
                    "work item command_id payload conflict",
                )
            if existing["status"] == "queued" and (
                existing["task_id"] not in self._jobs or self._jobs[existing["task_id"]].done()
            ):
                self._schedule_dispatch(owner, existing["task_id"])
            return self._create_response(existing, idempotent_replay=True)

        origin = self._repos.thread_repo.get(body.origin_thread_id.strip())
        if origin is None or int(origin.user_id) != int(owner):
            raise OctopError(ErrorCode.WORK_ITEM_INVALID, "origin_thread not found for owner")
        agent = self._repos.agent_repo.get(body.agent_id.strip())
        if agent is None:
            raise OctopError(ErrorCode.AGENT_NOT_FOUND, "agent not found")
        if agent.user_id is not None and int(agent.user_id) != int(owner) and not int(
            getattr(agent, "is_shared", 0) or 0
        ):
            raise OctopError(ErrorCode.WORK_ITEM_FORBIDDEN, "agent not accessible")
        if origin.agent_id != body.agent_id.strip():
            raise OctopError(
                ErrorCode.WORK_ITEM_INVALID, "origin_thread agent_id mismatch"
            )

        user = self._repos.user_repo.get(owner)
        if user is not None and getattr(user, "disabled", False):
            raise OctopError(ErrorCode.USER_DISABLED, "user disabled")

        target_kind = (body.execution.target_kind or "device").strip() or "device"
        device_id = (body.execution.device_id or "").strip() or None
        working_dir = body.execution.working_dir
        if device_id and self._devices is not None:
            try:
                self._devices.owned(owner, device_id)
            except OctopError:
                raise
            except Exception as exc:
                raise OctopError(
                    ErrorCode.WORK_ITEM_FORBIDDEN, "device not authorized"
                ) from exc

        task_id = new_ulid()
        artifacts = [r.model_dump() for r in body.resources]
        row = self._repo.insert(
            {
                "task_id": task_id,
                "owner_user_id": owner,
                "agent_id": body.agent_id.strip(),
                "command_id": command_id,
                "origin_thread_id": body.origin_thread_id.strip(),
                "title": body.title.strip(),
                "instructions": body.instructions,
                "status": "queued",
                "target_kind": target_kind,
                "device_id": device_id,
                "working_dir": working_dir,
                "artifacts": artifacts,
            }
        )
        # Store fingerprint in a phase event for conflict checks on replay.
        self._record_event(
            owner=owner,
            task=row,
            kind="work_item",
            status="queued",
            payload={"phase": "created", "fingerprint": fingerprint},
            event_id=f"work:{task_id}:created",
        )
        await self._emit_task(row, reason="created")
        self._schedule_dispatch(owner, task_id)
        return self._create_response(row, idempotent_replay=False)

    def _fingerprint_of(self, row: dict[str, Any]) -> dict[str, Any]:
        events = self._repos.run_event_repo.list_for_work_item(
            int(row["owner_user_id"]), row["task_id"], limit=5, kind="work_item"
        )
        for event in events:
            fp = (event.get("payload") or {}).get("fingerprint")
            if isinstance(fp, dict):
                return fp
        return {
            "agent_id": row["agent_id"],
            "origin_thread_id": row["origin_thread_id"],
            "title": row["title"],
            "instructions": row["instructions"],
            "execution": {
                "target_kind": row["target_kind"],
                "device_id": row["device_id"],
                "working_dir": row["working_dir"],
            },
            "resources": row.get("artifacts") or [],
        }

    @staticmethod
    def _create_response(row: dict[str, Any], *, idempotent_replay: bool) -> dict[str, Any]:
        return {
            "task_id": row["task_id"],
            "status": row["status"],
            "agent_id": row["agent_id"],
            "origin_thread_id": row["origin_thread_id"],
            "worker_thread_id": row["worker_thread_id"],
            "current_run_id": row["current_run_id"],
            "current_attempt_id": row["current_attempt_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "idempotent_replay": idempotent_replay,
            "schema_version": WORK_ITEM_SCHEMA_VERSION,
        }

    def _schedule_dispatch(self, owner: int, task_id: str) -> None:
        if task_id in self._jobs and not self._jobs[task_id].done():
            return

        async def _runner() -> None:
            async with self._bg_slots:
                await self._dispatch(owner, task_id)

        self._jobs[task_id] = asyncio.create_task(_runner(), name=f"work-item:{task_id}")

        def _done(task: asyncio.Task[None]) -> None:
            self._jobs.pop(task_id, None)
            with contextlib.suppress(asyncio.CancelledError, Exception):
                task.result()

        self._jobs[task_id].add_done_callback(_done)

    async def _dispatch(self, owner: int, task_id: str) -> None:
        row = self._repo.get(owner, task_id)
        if row is None:
            return
        if row["status"] in _TERMINAL:
            return
        user = self._repos.user_repo.get(owner)
        if user is not None and getattr(user, "disabled", False):
            return
        try:
            session_key = f"{row['agent_id']}:dashboard:{owner}:work-item-{task_id}"
            worker_thread_id = await self._gateway.thread_registry.get_or_create_by_key(
                session_key=session_key,
                agent_id=row["agent_id"],
                user_id=owner,
                channel_type="dashboard",
                channel_metadata={"work_item_id": task_id, "kind": "work_item"},
            )
            run_id = new_ulid()
            attempt_id = new_ulid()
            context_id = None
            if (
                self._execution is not None
                and (row.get("device_id") or (row.get("target_kind") or "") == "local")
            ):
                try:
                    ctx = self._execution.resolve(
                        owner,
                        target_kind=row["target_kind"] or "device",
                        device_id=row["device_id"],
                        working_dir=row["working_dir"],
                        agent_id=row["agent_id"],
                        thread_id=worker_thread_id,
                        run_id=run_id,
                        work_item_id=task_id,
                    )
                    context_id = getattr(ctx, "context_id", None) or (
                        ctx.get("context_id") if isinstance(ctx, dict) else None
                    )
                except OctopError as exc:
                    self._fail(owner, task_id, str(exc), block_reason=exc.code.value)
                    return
            else:
                context_id = self._create_context(owner, row, worker_thread_id, run_id)

            row = self._repo.update(
                owner,
                task_id,
                status="running",
                worker_thread_id=worker_thread_id,
                current_run_id=run_id,
                current_attempt_id=attempt_id,
                context_id=context_id,
            ) or row
            self._record_event(
                owner=owner,
                task=row,
                kind="work_item",
                status="running",
                payload={
                    "phase": "running",
                    "attempt_id": attempt_id,
                    "active_tools": [],
                },
                event_id=f"work:{task_id}:attempt:{attempt_id}:start",
                run_id=run_id,
                context_id=context_id,
            )
            await self._emit_task(row, reason="running")

            if row.get("cancel_requested"):
                if not self._has_open_external_jobs(owner, task_id):
                    await self._confirm_cancel(owner, task_id)
                return

            output = await self._run_worker_turn(row, session_key=session_key)
            row = self._repo.get(owner, task_id) or row
            if row.get("cancel_requested"):
                if not self._has_open_external_jobs(owner, task_id):
                    await self._confirm_cancel(owner, task_id)
                return
            await self._complete(owner, task_id, output=output or "")
        except asyncio.CancelledError:
            row = self._repo.get(owner, task_id)
            if (
                row is not None
                and row.get("cancel_requested")
                and not self._has_open_external_jobs(owner, task_id)
            ):
                await self._confirm_cancel(owner, task_id)
            raise
        except Exception:
            logger.exception("work item dispatch failed task=%s", task_id)
            self._fail(owner, task_id, "worker dispatch failed", block_reason="dispatch_error")

    def _create_context(
        self, owner: int, row: dict[str, Any], worker_thread_id: str, run_id: str
    ) -> str | None:
        from octop.infra.db.repos.execution import ExecutionContextRepo

        repo = ExecutionContextRepo(self._repos.db)
        try:
            ctx = repo.create(
                owner_user_id=owner,
                device_id=row["device_id"],
                working_dir=row["working_dir"],
                policy_revision=0,
                grant_version=0,
                work_mode="agentic",
                source="work_item",
                target_kind=row["target_kind"] or "device",
                agent_id=row["agent_id"],
                thread_id=worker_thread_id,
                run_id=run_id,
                work_item_id=row["task_id"],
            )
            return ctx.context_id
        except TypeError:
            ctx = repo.create(
                owner_user_id=owner,
                device_id=row["device_id"],
                working_dir=row["working_dir"],
                policy_revision=0,
                grant_version=0,
                work_mode="agentic",
                source="work_item",
                target_kind=row["target_kind"] or "device",
                agent_id=row["agent_id"],
                thread_id=worker_thread_id,
                run_id=run_id,
            )
            # Best-effort attach work_item_id if column exists.
            with contextlib.suppress(Exception), self._repos.db.transaction() as conn:
                conn.execute(
                    "UPDATE execution_contexts SET work_item_id = ? WHERE context_id = ?",
                    (row["task_id"], ctx.context_id),
                )
            return ctx.context_id
        except Exception:
            logger.exception("execution context create failed for work item %s", row["task_id"])
            return None

    async def _run_worker_turn(self, row: dict[str, Any], *, session_key: str) -> str:
        """Run the worker turn via CronDelivery when available; else record a phase-only turn."""
        if self._delivery is not None:
            from octop.infra.cron.delivery import CronDeliveryCommand

            command = CronDeliveryCommand(
                cron_id=row["task_id"],
                cron_name=row["title"],
                agent_id=row["agent_id"],
                user_id=int(row["owner_user_id"]),
                session_key=session_key,
                prompt=row["instructions"] or row["title"],
                fresh_thread=False,
                task_type="agent",
                model=None,
                mcp_servers=(),
                device_id=row["device_id"],
                task_run_id=row["current_run_id"],
                device_grant_version=(
                    self._devices.owned(int(row["owner_user_id"]), row["device_id"]).grant_version
                    if row["device_id"] and self._devices is not None
                    else 0
                ),
            )
            return str(await self._delivery.deliver(command) or "")
        # Lightweight path for tests without harness: durable phase event only.
        self._record_event(
            owner=int(row["owner_user_id"]),
            task=row,
            kind="work_item",
            status="running",
            payload={"phase": "tool_running", "active_tools": [], "message": "worker ready"},
            event_id=f"work:{row['task_id']}:attempt:{row['current_attempt_id']}:phase",
            run_id=row["current_run_id"],
            context_id=row.get("context_id"),
        )
        await self._emit_task(row, reason="progress", phase="tool_running")
        return row["instructions"] or row["title"]

    async def _complete(self, owner: int, task_id: str, *, output: str) -> None:
        row = self._repo.get(owner, task_id)
        if row is None or row["status"] in _TERMINAL:
            return
        summary = (output or "").strip()[:4000] or f"Work item {row['title']} completed."
        row = self._repo.update(
            owner,
            task_id,
            status="completed",
            reported_outcome=summary[:1000],
            block_reason=None,
        ) or row
        attempt_id = row["current_attempt_id"] or "final"
        self._record_event(
            owner=owner,
            task=row,
            kind="work_item",
            status="completed",
            payload={"phase": "completed", "attempt_id": attempt_id, "active_tools": []},
            event_id=f"work:{task_id}:attempt:{attempt_id}:done",
            run_id=row["current_run_id"],
            context_id=row.get("context_id"),
        )
        await self._deliver_result(row, summary=summary, attempt_id=attempt_id)
        await self._emit_task(row, reason="completed")

    def _fail(
        self, owner: int, task_id: str, message: str, *, block_reason: str | None = None
    ) -> None:
        row = self._repo.update(
            owner,
            task_id,
            status="failed",
            reported_outcome=message[:1000],
            block_reason=block_reason,
        )
        if row is None:
            return
        self._record_event(
            owner=owner,
            task=row,
            kind="work_item",
            status="failed",
            payload={"phase": "failed", "message": message[:500], "active_tools": []},
            event_id=f"work:{task_id}:failed:{new_ulid()}",
            run_id=row.get("current_run_id"),
            context_id=row.get("context_id"),
        )
        asyncio.create_task(self._emit_task(row, reason="failed"), name=f"work-fail:{task_id}")

    async def _deliver_result(
        self, row: dict[str, Any], *, summary: str, attempt_id: str
    ) -> None:
        origin_id = row.get("origin_thread_id")
        if not origin_id:
            return
        origin = self._repos.thread_repo.get(origin_id)
        if origin is None:
            return  # tombstone — skip history append / thread.changed (DEC-0043-08)
        message_id = f"work:{row['task_id']}:result:{attempt_id}"
        if self._repos.thread_message_repo.has_message_id(origin_id, message_id) is True:
            await self._gateway.emit_thread_changed(
                owner_user_id=int(row["owner_user_id"]),
                agent_id=row["agent_id"],
                thread_id=origin_id,
                reason="completed",
                run_id=row.get("current_run_id"),
            )
            return
        try:
            harness = None
            if self._registry is not None:
                with contextlib.suppress(Exception):
                    harness = self._registry.get_agent(row["agent_id"])
            if harness is not None and hasattr(harness, "aappend_messages"):
                from langchain_core.messages import AIMessage

                msg = AIMessage(content=summary)
                msg.id = message_id
                await harness.aappend_messages(origin_id, [msg])
            else:
                import json as _json

                from octop.infra.db.repos.thread_messages import ThreadMessageInput

                self._repos.thread_message_repo.append_legacy_interval(
                    origin_id,
                    [
                        ThreadMessageInput(
                            message_id=message_id,
                            role="assistant",
                            message_json=_json.dumps(
                                {"type": "ai", "content": summary, "id": message_id},
                                ensure_ascii=False,
                            ),
                            created_at=int(time.time()),
                        )
                    ],
                )
        except Exception:
            logger.exception(
                "work item result append failed task=%s origin=%s", row["task_id"], origin_id
            )
            return
        await self._gateway.emit_thread_changed(
            owner_user_id=int(row["owner_user_id"]),
            agent_id=row["agent_id"],
            thread_id=origin_id,
            reason="completed",
            run_id=row.get("current_run_id"),
        )

    # ── read APIs (progress = read-only) ────────────────────────────────

    def list_items(
        self,
        owner: int,
        *,
        origin_thread_id: str | None = None,
        status_group: str = "open",
        before: float | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        fetch = min(max(int(limit), 1), 200) + 1
        rows = self._repo.list(
            owner,
            origin_thread_id=origin_thread_id,
            status_group=status_group,
            before=before,
            limit=fetch,
        )
        has_more = len(rows) > limit
        items = rows[:limit]
        return {
            "items": [
                {
                    "task_id": r["task_id"],
                    "title": r["title"],
                    "status": r["status"],
                    "origin_thread_id": r["origin_thread_id"],
                    "updated_at": r["updated_at"],
                    "cancel_requested": r["cancel_requested"],
                }
                for r in items
            ],
            "has_more": has_more,
            "schema_version": WORK_ITEM_SCHEMA_VERSION,
        }

    def detail(self, owner: int, task_id: str) -> dict[str, Any]:
        row = self._require(owner, task_id)
        progress = self._progress_of(row)
        origin_missing = False
        if row.get("origin_thread_id"):
            origin_missing = self._repos.thread_repo.get(row["origin_thread_id"]) is None
        return {
            "task_id": row["task_id"],
            "title": row["title"],
            "instructions": row["instructions"],
            "status": row["status"],
            "reported_outcome": row["reported_outcome"],
            "cancel_requested": row["cancel_requested"],
            "cancel_requested_at": row["cancel_requested_at"],
            "agent_id": row["agent_id"],
            "origin_thread_id": row["origin_thread_id"],
            "origin_thread_missing": origin_missing,
            "worker_thread_id": row["worker_thread_id"],
            "current_run_id": row["current_run_id"],
            "current_attempt_id": row["current_attempt_id"],
            "execution": {
                "target_kind": row["target_kind"],
                "device_id": row["device_id"],
                "working_dir": row["working_dir"],
                "context_id": row["context_id"],
            },
            "progress": progress,
            "artifacts": row.get("artifacts") or [],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "schema_version": WORK_ITEM_SCHEMA_VERSION,
        }

    def progress(self, owner: int, task_id: str) -> dict[str, Any]:
        """Read-only progress subset — must not mutate worker / steer / queues."""
        row = self._require(owner, task_id)
        progress = self._progress_of(row)
        return {
            "task_id": row["task_id"],
            "status": row["status"],
            "cancel_requested": row["cancel_requested"],
            "worker_thread_id": row["worker_thread_id"],
            "current_run_id": row["current_run_id"],
            "current_attempt_id": row["current_attempt_id"],
            "progress": progress,
            "schema_version": WORK_ITEM_SCHEMA_VERSION,
        }

    def events(
        self,
        owner: int,
        task_id: str,
        *,
        before: int | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        self._require(owner, task_id)
        fetch = min(max(int(limit), 1), 200) + 1
        rows = self._repos.run_event_repo.list_for_work_item(
            owner, task_id, before=before, limit=fetch
        )
        has_more = len(rows) > limit
        events = []
        for event in rows[:limit]:
            payload = event.get("payload") or {}
            events.append(
                {
                    "event_id": event["event_id"],
                    "seq": event["seq"],
                    "created_at": event["created_at"],
                    "kind": payload.get("phase") and "phase" or event["kind"],
                    "status": event["status"],
                    "phase": payload.get("phase"),
                    "active_tools": [
                        str(n) for n in (payload.get("active_tools") or []) if str(n).strip()
                    ],
                    "block_reason": payload.get("block_reason"),
                    "message": payload.get("message"),
                    "artifacts": payload.get("artifacts") or [],
                    "job_id": payload.get("job_id"),
                    "attempt_id": payload.get("attempt_id"),
                }
            )
        return {
            "events": events,
            "has_more": has_more,
            "schema_version": WORK_ITEM_SCHEMA_VERSION,
        }

    def _progress_of(self, row: dict[str, Any]) -> dict[str, Any]:
        events = self._repos.run_event_repo.list_for_work_item(
            int(row["owner_user_id"]), row["task_id"], limit=1
        )
        phase = None
        active_tools: list[str] = []
        last_event_at = row["updated_at"]
        if events:
            payload = events[0].get("payload") or {}
            phase = payload.get("phase")
            active_tools = [
                str(n) for n in (payload.get("active_tools") or []) if str(n).strip()
            ]
            last_event_at = events[0].get("created_at") or last_event_at
        return {
            "phase": phase,
            "active_tools": active_tools,
            "last_event_at": last_event_at,
            "block_reason": row.get("block_reason"),
            "needs_approval": row.get("needs_approval", False),
            "needs_credential": row.get("needs_credential", False),
            "permission_denied": row.get("permission_denied", False),
        }

    # ── inputs / cancel ─────────────────────────────────────────────────

    async def add_input(self, owner: int, task_id: str, body: WorkItemInputCreate) -> dict[str, Any]:
        row = self._require(owner, task_id)
        if row["status"] in _TERMINAL:
            raise OctopError(
                ErrorCode.WORK_ITEM_RUN_CONFLICT, "work item already terminal"
            )
        if body.target_run_id and body.target_run_id != row.get("current_run_id"):
            raise OctopError(
                ErrorCode.WORK_ITEM_RUN_CONFLICT, "target_run_id is not current"
            )
        if body.target_attempt_id and body.target_attempt_id != row.get("current_attempt_id"):
            raise OctopError(
                ErrorCode.WORK_ITEM_RUN_CONFLICT, "target_attempt_id is not current"
            )
        try:
            saved = self._repo.insert_input(
                {
                    "input_id": new_ulid(),
                    "task_id": task_id,
                    "owner_user_id": owner,
                    "command_id": body.command_id.strip(),
                    "target_run_id": body.target_run_id,
                    "target_attempt_id": body.target_attempt_id,
                    "status": "accepted",
                    "payload": {"text": body.text},
                }
            )
        except ValueError as exc:
            if str(exc) == "command_conflict":
                raise OctopError(
                    ErrorCode.WORK_ITEM_COMMAND_CONFLICT, "input command_id conflict"
                ) from exc
            raise
        row = self._repo.update(owner, task_id, status="waiting_input") or row
        self._record_event(
            owner=owner,
            task=row,
            kind="work_item",
            status="waiting_input",
            payload={
                "phase": "input_accepted",
                "attempt_id": row.get("current_attempt_id"),
                "message": "input accepted",
                "active_tools": [],
            },
            event_id=f"work:{task_id}:input:{saved['input_id']}",
            run_id=row.get("current_run_id"),
            context_id=row.get("context_id"),
        )
        # Inputs bind to the worker — never 0033 steer / origin queue (DEC-0043-05).
        await self._emit_task(row, reason="waiting")
        await self._inject_worker_input(row, saved)
        return {
            "input_id": saved["input_id"],
            "task_id": task_id,
            "status": saved["status"],
            "schema_version": WORK_ITEM_SCHEMA_VERSION,
        }

    async def cancel(self, owner: int, task_id: str, body: WorkItemCancel) -> dict[str, Any]:
        row = self._require(owner, task_id)
        if body.scope == "attempt":
            if not body.attempt_id:
                raise OctopError(ErrorCode.WORK_ITEM_INVALID, "attempt_id required")
            if body.attempt_id != row.get("current_attempt_id"):
                raise OctopError(
                    ErrorCode.WORK_ITEM_RUN_CONFLICT, "attempt_id is not current"
                )
        if row["status"] == "cancelled":
            return {
                "task_id": task_id,
                "cancel_requested": True,
                "cancel_requested_at": row["cancel_requested_at"],
                "status": "cancelled",
                "terminated": True,
                "schema_version": WORK_ITEM_SCHEMA_VERSION,
            }
        now = time.time()
        if not row["cancel_requested"]:
            row = self._repo.update(
                owner,
                task_id,
                cancel_requested=1,
                cancel_requested_at=now,
            ) or row
            self._record_event(
                owner=owner,
                task=row,
                kind="work_item",
                status=row["status"],
                payload={
                    "phase": "cancel_requested",
                    "attempt_id": body.attempt_id or row.get("current_attempt_id"),
                    "active_tools": [],
                },
                event_id=f"work:{task_id}:cancel:{body.command_id.strip()}",
                run_id=row.get("current_run_id"),
                context_id=row.get("context_id"),
            )
            await self._emit_task(row, reason="progress", phase="cancel_requested")

        terminated = False
        job = self._jobs.get(task_id)
        if job is not None and not job.done():
            job.cancel()
        row = self._repo.get(owner, task_id) or row
        if self._should_confirm_cancel_now(row):
            await self._confirm_cancel(owner, task_id)
            row = self._repo.get(owner, task_id) or row
            terminated = row["status"] == "cancelled"
        elif row["status"] in _TERMINAL:
            terminated = row["status"] == "cancelled"

        return {
            "task_id": task_id,
            "cancel_requested": True,
            "cancel_requested_at": row["cancel_requested_at"] or now,
            "status": row["status"],
            "terminated": terminated,
            "schema_version": WORK_ITEM_SCHEMA_VERSION,
        }

    async def _confirm_cancel(self, owner: int, task_id: str) -> None:
        row = self._repo.update(owner, task_id, status="cancelled") or self._repo.get(
            owner, task_id
        )
        if row is None:
            return
        self._record_event(
            owner=owner,
            task=row,
            kind="work_item",
            status="cancelled",
            payload={"phase": "cancelled", "active_tools": []},
            event_id=f"work:{task_id}:cancelled",
            run_id=row.get("current_run_id"),
            context_id=row.get("context_id"),
        )
        await self._emit_task(row, reason="cancelled")

    def mark_unknown(self, owner: int, task_id: str, *, reason: str = "unconfirmed") -> None:
        """Surface unknown without replaying side-effect tools (DEC-0043-13 / AC-06)."""
        row = self._repo.update(
            owner, task_id, status="unknown", block_reason=reason
        )
        if row is None:
            return
        self._record_event(
            owner=owner,
            task=row,
            kind="work_item",
            status="unknown",
            payload={"phase": "unknown", "block_reason": reason, "active_tools": []},
            event_id=f"work:{task_id}:unknown:{new_ulid()}",
            run_id=row.get("current_run_id"),
            context_id=row.get("context_id"),
        )
        asyncio.create_task(self._emit_task(row, reason="unknown"), name=f"work-unk:{task_id}")

    # ── helpers ─────────────────────────────────────────────────────────

    def _has_open_external_jobs(self, owner: int, task_id: str) -> bool:
        """True when Jobs reconciler still has non-terminal job events for this item."""
        events = self._repos.run_event_repo.list_for_work_item(
            owner, task_id, kind="job", limit=200
        )
        if any((event.get("status") or "") in _OPEN_JOB_STATUSES for event in events):
            return True
        # Belt: older job rows may lack work_item_id; join via work item context_id.
        row = self._repo.get(owner, task_id)
        context_id = row.get("context_id") if row else None
        if not context_id:
            return False
        with self._repos.db.connect() as conn:
            rows = conn.execute(
                "SELECT status FROM run_events "
                "WHERE owner_user_id = ? AND context_id = ? AND kind = ?",
                (owner, context_id, "job"),
            ).fetchall()
        return any((r["status"] or "") in _OPEN_JOB_STATUSES for r in rows)

    def _should_confirm_cancel_now(self, row: dict[str, Any]) -> bool:
        """DEC-0043-09: terminal cancel only with no open Jobs and in-process work finished."""
        owner = int(row["owner_user_id"])
        task_id = row["task_id"]
        if self._has_open_external_jobs(owner, task_id):
            return False
        if row["status"] == "queued" and not row.get("worker_thread_id"):
            return True
        job = self._jobs.get(task_id)
        return job is None or job.done()

    async def _inject_worker_input(self, row: dict[str, Any], saved: dict[str, Any]) -> None:
        """Append accepted input onto the worker thread (never origin / 0033 steer)."""
        worker_id = row.get("worker_thread_id")
        if not worker_id:
            return
        if self._repos.thread_repo.get(worker_id) is None:
            return
        message_id = f"work:{row['task_id']}:input:{saved['input_id']}"
        if self._repos.thread_message_repo.has_message_id(worker_id, message_id) is True:
            return
        text = str((saved.get("payload") or {}).get("text") or "")
        try:
            harness = None
            if self._registry is not None:
                with contextlib.suppress(Exception):
                    harness = self._registry.get_agent(row["agent_id"])
            if harness is not None and hasattr(harness, "aappend_messages"):
                from langchain_core.messages import HumanMessage

                msg = HumanMessage(content=text)
                msg.id = message_id
                await harness.aappend_messages(worker_id, [msg])
            else:
                import json as _json

                from octop.infra.db.repos.thread_messages import ThreadMessageInput

                self._repos.thread_message_repo.append_legacy_interval(
                    worker_id,
                    [
                        ThreadMessageInput(
                            message_id=message_id,
                            role="user",
                            message_json=_json.dumps(
                                {"type": "human", "content": text, "id": message_id},
                                ensure_ascii=False,
                            ),
                            created_at=int(time.time()),
                        )
                    ],
                )
        except Exception:
            logger.exception(
                "work item input inject failed task=%s worker=%s",
                row["task_id"],
                worker_id,
            )

    def _require(self, owner: int, task_id: str) -> dict[str, Any]:
        row = self._repo.get(owner, task_id)
        if row is None:
            raise OctopError(ErrorCode.WORK_ITEM_NOT_FOUND, "work item not found")
        return row

    def _record_event(
        self,
        *,
        owner: int,
        task: dict[str, Any],
        kind: str,
        status: str,
        payload: dict[str, Any],
        event_id: str,
        run_id: str | None = None,
        context_id: str | None = None,
    ) -> None:
        thread_id = task.get("worker_thread_id") or task.get("origin_thread_id")
        if thread_id and self._repos.thread_repo.get(thread_id) is None:
            alt = task.get("origin_thread_id")
            thread_id = alt if alt and self._repos.thread_repo.get(alt) is not None else None
        self._repos.run_event_repo.save(
            event_id=event_id,
            owner=owner,
            agent_id=task["agent_id"],
            thread_id=thread_id,
            run_id=run_id or task.get("current_run_id") or task["task_id"],
            context_id=context_id or task.get("context_id"),
            kind=kind,
            status=status,
            payload=payload,
            work_item_id=task["task_id"],
        )

    async def _emit_task(
        self,
        row: dict[str, Any],
        *,
        reason: str,
        status_override: str | None = None,
        phase: str | None = None,
    ) -> None:
        await self._gateway.emit_task_changed(
            owner_user_id=int(row["owner_user_id"]),
            task_id=row["task_id"],
            agent_id=row["agent_id"],
            reason=reason,
            status=status_override or row["status"],
            origin_thread_id=row.get("origin_thread_id"),
            run_id=row.get("current_run_id"),
            updated_at=row.get("updated_at"),
            phase=phase,
        )


__all__ = ["WorkItemsService"]
