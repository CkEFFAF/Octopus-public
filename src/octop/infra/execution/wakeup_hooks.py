"""Scoped, durable events that wake an expert without holding a chat turn."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import time
from typing import TYPE_CHECKING, Any

from octop.i18n import tr
from octop.infra.devices.protocol import resolve_default_device_server
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.locale import resolve_user_locale

if TYPE_CHECKING:
    from octop.infra.cron.manager import CronManager
    from octop.infra.execution.service import ExecutionService


class WakeupHookService:
    def __init__(self, execution: ExecutionService) -> None:
        self.execution = execution
        self.repos = execution.devices.repos
        self.events = self.repos.run_event_repo

    def _scope(self, row: dict[str, Any]) -> None:
        owner = int(row["owner_user_id"])
        user = self.repos.user_repo.get(owner)
        agent = self.repos.agent_repo.get(row["agent_id"])
        thread = self.repos.thread_repo.get(row["thread_id"])
        if (
            not user
            or user.disabled
            or not agent
            or agent.user_id != owner
            or not thread
            or (thread.user_id, thread.agent_id) != (owner, row["agent_id"])
        ):
            raise OctopError(ErrorCode.FORBIDDEN, "wakeup hook origin unavailable")

    def _token(self, row: dict[str, Any]) -> str:
        secret = self.repos.secret_repo.get("jwt")
        if not secret:
            raise OctopError(ErrorCode.INTERNAL_ERROR, "wakeup credentials unavailable")
        message = f"wakeup:{row['owner_user_id']}:{row['event_id']}".encode()
        return "owh_" + hmac.new(secret, message, hashlib.sha256).hexdigest()

    def register(
        self,
        owner: int,
        agent: str,
        thread_id: str,
        context_id: str | None = None,
        *,
        title: str,
        event_type: str,
        purpose: str,
        idempotency_key: str,
        expires_in: int = 604800,
        job_event_id: str | None = None,
        include_token: bool = True,
        delivery_mode: str = "wake",
        resume_mode: str = "observe",
    ) -> dict[str, Any]:
        context = self.execution.get(owner, context_id) if context_id else None
        if context and (context.agent_id, context.thread_id) != (agent, thread_id):
            raise OctopError(
                ErrorCode.FORBIDDEN, "wakeup hook requires this expert's original thread"
            )
        self._scope({"owner_user_id": owner, "agent_id": agent, "thread_id": thread_id})
        if delivery_mode not in {"wake", "progress", "signal"}:
            raise ValueError("delivery_mode must be wake, progress or signal")
        if resume_mode not in {"observe", "continue"}:
            raise ValueError("resume_mode must be observe or continue")
        if resume_mode == "continue" and (context is None or delivery_mode != "wake"):
            raise ValueError("continuation requires a bound execution source and wake delivery")
        for value, maximum in (
            (title, 120),
            (event_type, 100),
            (purpose, 2000),
            (idempotency_key, 200),
        ):
            if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                raise ValueError("invalid wakeup hook field")
        if (
            any(char in title + event_type for char in "\r\n\x00")
            or not 60 <= expires_in <= 30 * 86400
        ):
            raise ValueError("invalid wakeup hook lifetime or label")
        identity = (
            "wh_"
            + hashlib.sha256(
                json.dumps([owner, agent, thread_id, context_id, idempotency_key]).encode()
            ).hexdigest()[:32]
        )
        payload = {
            "title": title.strip(),
            "event_type": event_type.strip(),
            "purpose": purpose.strip(),
            "job_event_id": job_event_id,
            "delivery_mode": delivery_mode,
            "resume_mode": resume_mode,
            "origin_work_mode": context.work_mode if context else None,
        }
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        row = self.events.wakeup_hook(identity)
        if row is None:
            self.events.save(
                event_id=identity,
                owner=owner,
                agent_id=agent,
                thread_id=thread_id,
                run_id=(context.run_id or context.context_id) if context else identity,
                context_id=context_id,
                kind="hook",
                status="waiting",
                payload={
                    **payload,
                    "fingerprint": fingerprint,
                    "expires_at": time.time() + expires_in,
                },
                replace=False,
            )
            row = self.events.wakeup_hook(identity)
        assert row is not None
        self._scope(row)
        if row["payload"].get("fingerprint") != fingerprint:
            raise ValueError("wakeup idempotency key reused with different event settings")
        result = self.public(row)
        if include_token:
            result["token"] = self._token(row)
            result["callback_url"] = (
                resolve_default_device_server().rstrip("/") + f"/api/wakeup-hooks/{identity}/fire"
            )
        return result

    @staticmethod
    def public(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "hook_id": row["event_id"],
            "status": row["status"],
            "agent_id": row["agent_id"],
            "thread_id": row["thread_id"],
            **{
                key: row["payload"].get(key)
                for key in (
                    "title",
                    "event_type",
                    "purpose",
                    "expires_at",
                    "received_at",
                    "cron_id",
                    "delivery_mode",
                    "resume_mode",
                    "origin_work_mode",
                    "progress",
                )
            },
        }

    def inspect(
        self, owner: int, agent: str, thread: str, hook_id: str | None = None
    ) -> dict[str, Any]:
        row = self.repos.thread_repo.get(thread)
        if not row or (row.user_id, row.agent_id) != (owner, agent):
            raise OctopError(ErrorCode.FORBIDDEN, "wakeup thread unavailable")
        rows = self.events.list(owner, agent, thread, limit=100, kind="hook")
        return {
            "hooks": [
                self.public(item) for item in rows if hook_id is None or item["event_id"] == hook_id
            ]
        }

    def cancel(self, owner: int, agent: str, thread: str, hook_id: str) -> dict[str, Any]:
        row = self.events.wakeup_hook(hook_id)
        if not row or (row["owner_user_id"], row["agent_id"], row["thread_id"]) != (
            owner,
            agent,
            thread,
        ):
            raise OctopError(ErrorCode.FORBIDDEN, "wakeup hook unavailable")
        for _ in range(3):
            if row["status"] in {"running", "completed", "cancelled"}:
                break
            if self.events.compare_payload(
                owner,
                hook_id,
                row["payload"],
                row["payload"],
                "cancelled",
                expected_status=row["status"],
            ):
                break
            current = self.events.wakeup_hook(hook_id)
            if current is None:
                raise OctopError(ErrorCode.NOT_FOUND, "wakeup hook unavailable")
            row = current
        current = self.events.wakeup_hook(hook_id)
        return {"hook_id": hook_id, "status": current["status"] if current else "unavailable"}

    def fire(self, hook_id: str, token: str, event_type: str, data: Any) -> dict[str, Any]:
        row = self.authenticate(hook_id, token)
        return self._queue(row, event_type, data)

    def authenticate(self, hook_id: str, token: str) -> dict[str, Any]:
        row = self.events.wakeup_hook(hook_id)
        if not row or not hmac.compare_digest(self._token(row), token):
            raise OctopError(ErrorCode.AUTH_FAILED, "invalid wakeup hook credential")
        self._scope(row)
        return row

    def _queue(self, row: dict[str, Any], event_type: str, data: Any) -> dict[str, Any]:
        self._scope(row)
        if event_type != row["payload"]["event_type"]:
            raise ValueError("wakeup event type does not match registration")
        encoded = json.dumps(data, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode()) > 8192:
            raise ValueError("wakeup event data exceeds 8192 bytes")
        if row["payload"].get("delivery_mode") == "progress":
            return self._progress(row, data)
        if row["status"] in {"queued", "scheduled", "running", "completed"}:
            return {"accepted": True, "duplicate": True, "hook_id": row["event_id"]}
        if row["status"] != "waiting" or row["payload"]["expires_at"] <= time.time():
            raise OctopError(ErrorCode.FORBIDDEN, "wakeup hook expired or cancelled")
        accepted = self.events.compare_payload(
            int(row["owner_user_id"]),
            row["event_id"],
            row["payload"],
            {**row["payload"], "data": data, "received_at": time.time()},
            "queued",
            expected_status="waiting",
        )
        if not accepted:
            current = self.events.wakeup_hook(row["event_id"])
            if not current or current["status"] not in {
                "queued",
                "scheduled",
                "running",
                "completed",
            }:
                raise OctopError(ErrorCode.FORBIDDEN, "wakeup hook cancelled or changed")
        return {"accepted": True, "duplicate": not accepted, "hook_id": row["event_id"]}

    def _progress(self, row: dict[str, Any], data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("progress data must be an object")
        percent, sequence = data.get("percent"), data.get("sequence")
        if percent is not None and (
            type(percent) not in {int, float}
            or not math.isfinite(percent)
            or not 0 <= percent <= 100
        ):
            raise ValueError("progress percent must be a number from 0 to 100")
        if sequence is not None and (type(sequence) is not int or sequence < 0):
            raise ValueError("progress sequence must be a nonnegative integer")
        if "done" in data and type(data["done"]) is not bool:
            raise ValueError("progress done must be a boolean")
        for key, maximum in (("phase", 100), ("message", 300)):
            if key in data and (not isinstance(data[key], str) or len(data[key]) > maximum):
                raise ValueError(f"progress {key} must be text up to {maximum} characters")
        for _ in range(3):
            payload = row["payload"]
            if (
                row["status"] not in {"waiting", "completed"}
                or payload["expires_at"] <= time.time()
            ):
                raise OctopError(ErrorCode.FORBIDDEN, "progress hook expired or cancelled")
            previous = payload.get("progress") or {}
            if sequence is None and "sequence" in previous:
                raise ValueError("progress sequence is required after sequenced reporting starts")
            if row["status"] == "completed" or (
                sequence is not None and sequence <= previous.get("sequence", -1)
            ):
                return {"accepted": True, "duplicate": True, "hook_id": row["event_id"]}
            progress = {
                "source": "script_reported",
                "updated_at": time.time(),
                **{
                    key: data[key]
                    for key in ("percent", "phase", "message", "sequence")
                    if key in data
                },
            }
            if self.events.compare_payload(
                int(row["owner_user_id"]),
                row["event_id"],
                payload,
                {**payload, "progress": progress},
                "completed" if data.get("done") else "waiting",
                expected_status="waiting",
            ):
                return {"accepted": True, "duplicate": False, "hook_id": row["event_id"]}
            current = self.events.wakeup_hook(row["event_id"])
            if current is None:
                break
            row = current
        raise OctopError(ErrorCode.WORKFLOW_CONFLICT, "progress update changed concurrently; retry")

    def progress_hook(
        self, owner: int, agent: str | None, thread: str | None, hook_id: str
    ) -> dict[str, Any]:
        row = self.events.wakeup_hook(hook_id)
        if (
            not row
            or (row["owner_user_id"], row["agent_id"], row["thread_id"]) != (owner, agent, thread)
            or row["payload"].get("delivery_mode") != "progress"
            or row["status"] not in {"waiting", "completed"}
            or row["payload"]["expires_at"] <= time.time()
        ):
            raise OctopError(ErrorCode.FORBIDDEN, "progress hook unavailable in this conversation")
        self._scope(row)
        return row

    def bind_progress(self, owner: int, job: dict[str, Any], hook_id: str) -> None:
        row = self.progress_hook(owner, job["agent_id"], job["thread_id"], hook_id)
        for _ in range(3):
            bound = row["payload"].get("job_event_id")
            if bound == job["event_id"]:
                return
            if bound:
                raise ValueError("progress hook already belongs to another job")
            if self.events.compare_payload(
                owner,
                row["event_id"],
                row["payload"],
                {**row["payload"], "job_event_id": job["event_id"]},
                row["status"],
                expected_status=row["status"],
            ):
                return
            current = self.events.wakeup_hook(hook_id)
            if current is None or current["status"] not in {"waiting", "completed"}:
                break
            row = current
        raise OctopError(
            ErrorCode.WORKFLOW_CONFLICT, "progress binding changed concurrently; retry"
        )

    def reserve_progress(
        self, owner: int, agent: str | None, thread: str | None, hook_id: str, submission: str
    ) -> None:
        for _ in range(3):
            row = self.progress_hook(owner, agent, thread, hook_id)
            existing = row["payload"].get("progress_submission")
            if existing == submission:
                return
            if existing or row["payload"].get("job_event_id"):
                raise ValueError("progress hook already belongs to another job submission")
            if self.events.compare_payload(
                owner,
                hook_id,
                row["payload"],
                {**row["payload"], "progress_submission": submission},
                row["status"],
                expected_status=row["status"],
            ):
                return
        raise OctopError(
            ErrorCode.WORKFLOW_CONFLICT, "progress reservation changed concurrently; retry"
        )

    async def tick(self, cron: CronManager) -> None:
        for job in self.events.jobs_without_progress_binding():
            try:
                self.bind_progress(
                    int(job["owner_user_id"]), job, job["payload"]["progress_hook_id"]
                )
            except (OctopError, ValueError):
                continue
        for job in self.events.jobs_without_completion_hook():
            locale = resolve_user_locale(
                user_repo=self.repos.user_repo, user_id=int(job["owner_user_id"])
            )
            try:
                self.register(
                    int(job["owner_user_id"]),
                    job["agent_id"],
                    job["thread_id"],
                    job["context_id"],
                    title=str(
                        job["payload"].get("title") or tr("execution.backgroundTask", locale)
                    ),
                    event_type="job.terminated",
                    purpose=tr("execution.jobCompletionPurpose", locale),
                    idempotency_key=job["event_id"],
                    job_event_id=job["event_id"],
                    resume_mode=job["payload"].get("resume_mode", "observe"),
                    include_token=False,
                )
            except (OctopError, ValueError):
                continue
        for row in self.events.pending_wakeup_hooks():
            try:
                if row["status"] == "waiting":
                    if row["payload"].get("expires_at", 0) <= time.time():
                        self.events.compare_payload(
                            int(row["owner_user_id"]),
                            row["event_id"],
                            row["payload"],
                            row["payload"],
                            "cancelled",
                            expected_status="waiting",
                        )
                        continue
                    observed_job = self.events.get(
                        int(row["owner_user_id"]), str(row["payload"].get("job_event_id") or "")
                    )
                    if not observed_job or observed_job["status"] not in {
                        "completed",
                        "failed",
                        "cancelled",
                    }:
                        continue
                    if row["payload"].get("delivery_mode") == "progress":
                        self.events.compare_payload(
                            int(row["owner_user_id"]),
                            row["event_id"],
                            row["payload"],
                            row["payload"],
                            "completed",
                            expected_status="waiting",
                        )
                        continue
                    self._queue(
                        row,
                        row["payload"]["event_type"],
                        {
                            "job_id": observed_job["payload"].get("job_id"),
                            "status": observed_job["status"],
                            "returncode": observed_job["payload"].get("returncode"),
                        },
                    )
                    refreshed = self.events.wakeup_hook(row["event_id"])
                    if refreshed is None:
                        continue
                    row = refreshed
                await self.schedule(row, cron)
            except (OctopError, ValueError):
                # A revoked/deleted origin must never target another thread.
                current = self.events.wakeup_hook(row["event_id"])
                if current and current["status"] in {"waiting", "queued"}:
                    self.events.compare_payload(
                        int(current["owner_user_id"]),
                        current["event_id"],
                        current["payload"],
                        current["payload"],
                        "blocked",
                        expected_status=current["status"],
                    )

    @staticmethod
    def delivery_prompt(repos: Any, row: dict[str, Any]) -> str:
        locale = resolve_user_locale(user_repo=repos.user_repo, user_id=row["owner_user_id"])
        facts = {key: row["payload"].get(key) for key in ("title", "event_type", "data")}
        return tr(
            "execution.wakeupPrompt",
            locale,
            purpose=row["payload"]["purpose"],
            mode=tr(
                "execution.wakeupContinue"
                if row["payload"].get("resume_mode") == "continue"
                else "execution.wakeupObserve",
                locale,
            ),
            data=json.dumps(facts, ensure_ascii=False),
        )

    async def schedule(self, row: dict[str, Any], cron: CronManager) -> None:
        from octop.infra.cron.manager import CronCreateSpec
        from octop.infra.cron.origin_target import ensure_pin_session
        from octop.infra.cron.self_reminder import (
            SELF_REMINDER_KIND,
            build_trigger,
            resolve_fire_at,
            stamp_origin_meta,
        )

        self._scope(row)
        if row["payload"].get("delivery_mode") == "signal":
            return
        if row["status"] != "queued":
            return
        owner = int(row["owner_user_id"])
        cron_id = "event-" + row["event_id"]
        if cron.get(cron_id) is None:
            session = ensure_pin_session(
                session_repo=self.repos.session_repo,
                thread_id=row["thread_id"],
                agent_id=row["agent_id"],
                user_id=owner,
            )
            trigger, meta = build_trigger(
                fire_at=resolve_fire_at(in_seconds=1), repeat_every_seconds=None
            )
            meta = stamp_origin_meta(meta, thread_id=row["thread_id"])
            meta.update(wakeup_hook_id=row["event_id"], wakeup_context_id=row["context_id"])
            prompt = self.delivery_prompt(self.repos, row)
            await cron.create(
                CronCreateSpec(
                    cron_id=cron_id,
                    agent_id=row["agent_id"],
                    user_id=owner,
                    name=row["payload"]["title"],
                    session_key=session.session_key,
                    trigger=trigger,
                    prompt=prompt,
                    fresh_thread=False,
                    task_type="agent",
                    kind=SELF_REMINDER_KIND,
                    meta=meta,
                )
            )
        self.events.compare_payload(
            owner,
            row["event_id"],
            row["payload"],
            {**row["payload"], "cron_id": cron_id},
            "scheduled",
            expected_status="queued",
        )
