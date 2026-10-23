"""Shared conversation metadata service for HTTP, background jobs and Agent tools."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from octop.infra.conversations.errors import generation_error_code
from octop.infra.conversations.generation import generate_json
from octop.infra.conversations.models import (
    BriefPatch,
    ConversationBrief,
    Coverage,
    DigestResult,
    EventPage,
    EventView,
    GeneratedBrief,
    GeneratedDigest,
    GeneratedTitle,
    HistoryBatchRequest,
    HistoryBatchView,
    JobView,
    MetadataSettings,
    ModelOption,
    SettingsView,
    SourceView,
)
from octop.infra.conversations.sources import message_source, output_json
from octop.infra.db.repos.usage import resolve_usage_window
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.model_diagnostics import output_issues, safe_diagnostics
from octop.infra.utils.ulid import new_ulid

logger = logging.getLogger(__name__)
PROMPT_VERSION = 2


def denied() -> OctopError:
    return OctopError(ErrorCode.FORBIDDEN, "conversation not accessible")


def conflict() -> OctopError:
    return OctopError(ErrorCode.WORKFLOW_CONFLICT, "METADATA_REVISION_CONFLICT")


class ConversationService:
    def __init__(
        self,
        manager: Any,
        timezone: str = "UTC",
        notify: Callable[[int, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self.manager, self.timezone, self.notify = manager, timezone, notify

    @property
    def repos(self) -> RepoBundle:
        return self.manager._repos  # type: ignore[no-any-return]

    @property
    def archive(self) -> Any:
        return (getattr(self.manager, "_native_management_context", None) or {}).get(
            "history_archive"
        )

    def _source_rows(self, thread: str, refs: set[str]) -> list[dict[str, Any]]:
        legacy = sorted(int(ref) for ref in refs if ref.isdigit())
        archived = sorted(
            int(ref[8:]) for ref in refs if ref.startswith("archive:") and ref[8:].isdigit()
        )
        rows = self.repos.conversation_metadata_repo.message_refs(thread, legacy)
        if archived and self.archive:
            rows.extend(
                self.archive.store.metadata_messages(
                    thread, identities=archived, limit=len(archived)
                )
            )
        return rows

    def scope(self, owner: int, agent: str, thread: str) -> Any:
        user = self.repos.user_repo.get(owner)
        row = self.repos.agent_repo.get(agent)
        conversation = self.repos.thread_repo.get(thread)
        if (
            user is None
            or user.disabled
            or row is None
            or conversation is None
            or (conversation.user_id, conversation.agent_id) != (owner, agent)
            or (row.user_id != owner and not row.is_shared)
        ):
            raise denied()
        return conversation

    def config(self, owner: int) -> MetadataSettings:
        return MetadataSettings.model_validate(
            self.repos.conversation_metadata_repo.settings(owner)
        )

    def resolve_model(self, owner: int, choice: str, title_choice: str = "account") -> str | None:
        if choice == "same":
            choice = title_choice
        if choice == "account":
            name, model = self.repos.settings_repo.get_active_model(owner)
            choice = f"{name}/{model}" if name and model else ""
        return (
            choice
            if choice and self.manager.providers_for_user(owner).is_model_ref_usable(choice)
            else None
        )

    def settings(self, owner: int) -> SettingsView:
        cfg = self.config(owner)
        store = self.manager.providers_for_user(owner)
        models = [
            ModelOption(value=f"{p.id}/{m.id}", label=f"{p.name or p.id} / {m.name or m.id}")
            for p in store.build_harness_configs()
            for m in p.models
            if m.enabled and "text" in m.input
        ]
        title = self.resolve_model(owner, cfg.title_model)
        brief = self.resolve_model(owner, cfg.brief_model, cfg.title_model)
        return SettingsView(
            **cfg.model_dump(),
            models=models,
            resolved_title_model=title,
            resolved_brief_model=brief,
            title_available=bool(title),
            brief_available=bool(brief),
        )

    def save_settings(self, owner: int, cfg: MetadataSettings) -> SettingsView:
        allowed = {option.value for option in self.settings(owner).models}
        current = self.config(owner)
        if cfg.title_model not in allowed | {
            "account",
            current.title_model,
        } or cfg.brief_model not in allowed | {
            "account",
            "same",
            current.brief_model,
        }:
            raise OctopError(ErrorCode.SLASH_BAD_ARGS, "METADATA_MODEL_UNAVAILABLE")
        if not self.repos.conversation_metadata_repo.save_settings(
            owner, cfg.revision, cfg.model_dump()
        ):
            raise conflict()
        if not (cfg.title_enabled or cfg.brief_enabled):
            self.repos.conversation_metadata_repo.cancel_jobs(owner, automatic=True)
        return self.settings(owner)

    @staticmethod
    def job_view(job: dict[str, Any]) -> JobView:
        return JobView(**{key: job[key] for key in JobView.model_fields})

    def request(self, owner: int, agent: str, thread: str, kind: str, command: str) -> JobView:
        self.scope(owner, agent, thread)
        if kind == "brief":
            self.repos.conversation_metadata_repo.enroll(thread)
        value = self.repos.conversation_metadata_repo.enqueue(
            owner, agent, thread, kind, {}, f"{owner}:{thread}:{kind}:{command}"
        )
        return self.job_view(value)

    def history_batch(self, owner: int) -> HistoryBatchView | None:
        value = self.repos.conversation_metadata_repo.history_batch(owner)
        return HistoryBatchView(**value) if value else None

    def cancel_history_batch(self, owner: int, identity: str) -> HistoryBatchView:
        repo = self.repos.conversation_metadata_repo
        if repo.batch(owner, identity) is None:
            raise OctopError(ErrorCode.NOT_FOUND, "metadata batch not found")
        repo.cancel_jobs(owner, batch=identity)
        value = repo.batch(owner, identity)
        assert value is not None
        return HistoryBatchView(**value)

    def cancel_job(self, owner: int, agent: str, thread: str, identity: str) -> JobView:
        self.job(owner, agent, thread, identity)
        self.repos.conversation_metadata_repo.cancel_jobs(owner, thread=thread, identity=identity)
        return self.job(owner, agent, thread, identity)

    def start_history_batch(self, owner: int, body: HistoryBatchRequest) -> HistoryBatchView:
        if body.thread_ids is not None:
            if body.agent_id is None:
                raise OctopError(
                    ErrorCode.SLASH_BAD_ARGS, "Agent required for selected conversations"
                )
            for thread in body.thread_ids:
                self.scope(owner, body.agent_id, thread)
        elif body.agent_id is not None:
            agent = self.repos.agent_repo.get(body.agent_id)
            if agent is None or (agent.user_id != owner and not agent.is_shared):
                raise denied()
        settings = self.settings(owner)
        if not settings.brief_available or (
            settings.title_enabled and not settings.title_available
        ):
            raise OctopError(ErrorCode.SLASH_BAD_ARGS, "METADATA_MODEL_UNAVAILABLE")
        return HistoryBatchView(
            **self.repos.conversation_metadata_repo.start_history_batch(
                owner, body.command_id, body.agent_id, body.thread_ids
            )
        )

    def job(self, owner: int, agent: str, thread: str, identity: str) -> JobView:
        self.scope(owner, agent, thread)
        row = self.repos.conversation_metadata_repo.job(owner, thread, identity)
        if row is None:
            raise OctopError(ErrorCode.NOT_FOUND, "metadata job not found")
        return self.job_view(row)

    def patch(self, owner: int, agent: str, thread: str, patch: BriefPatch) -> ConversationBrief:
        current = self.brief(owner, agent, thread)
        changes = patch.model_dump(exclude_unset=True, exclude={"expected_revision"})
        if patch.objective is not None and patch.objective != current.overview["objective"]:
            changes.update(
                objective_version=current.objective_version + 1,
                work_state="in_progress",
                acceptance=None,
            )
        if "work_state" in changes:
            changes.setdefault("objective_version", current.objective_version)
            changes["acceptance"] = (
                {"actor": owner, "at": time.time()} if patch.work_state == "completed" else None
            )
        if not self.repos.conversation_metadata_repo.patch_manual(
            thread, patch.expected_revision, changes
        ):
            raise conflict()
        return self.brief(owner, agent, thread)

    def title_action(
        self, owner: int, agent: str, thread: str, expected: int, action: str, title: str | None
    ) -> ConversationBrief:
        self.scope(owner, agent, thread)
        if action == "apply":
            title = GeneratedTitle(title=title or "").title
        if not self.repos.conversation_metadata_repo.title_action(thread, expected, action, title):
            raise conflict()
        if action == "restore":
            self.repos.conversation_metadata_repo.enroll(thread)
            self.request(owner, agent, thread, "brief", new_ulid())
        return self.brief(owner, agent, thread)

    def _facts(self, owner: int, agent: str, thread: str) -> dict[str, Any]:
        active = self.repos.run_event_repo.active(owner, agent, thread, limit=201)
        live = self.manager.steering_status(agent, thread)
        fresh = [
            r
            for r in active
            if time.time() - r["updated_at"] <= 45
            and (r["payload"].get("observation") or {}).get("status") != "unavailable"
        ]
        state = "running" if live or fresh else "unknown" if active else "idle"
        live_status = str((live or {}).get("status") or (live or {}).get("state") or "")
        if live_status in {"paused", "waiting_user", "waiting_approval", "queued"}:
            state = live_status
        runtime = getattr(self.manager, "_conversation_runtime", {})
        if runtime.get("turn_active") and runtime["turn_active"](thread):
            state = "running"
        conversation = self.repos.thread_repo.get(thread)
        if (
            runtime.get("pending")
            and conversation
            and runtime["pending"](conversation.session_key, agent_id=agent)
        ):
            state = "waiting_approval"
        queued = self.repos.chat_input_repo.list(owner, agent, thread)
        if state == "idle" and any(r["status"] == "queued" for r in queued):
            state = "queued"
        recent = self.repos.run_event_repo.list(owner, agent, thread, limit=1)
        if state == "idle" and recent and recent[0]["status"] == "failed":
            state = "failed"
        plans = self.repos.workbench_repo.list(owner, agent, thread, "plan", limit=100)
        workflows = self.repos.run_event_repo.list(owner, agent, thread, kind="workflow", limit=51)
        checks = [
            (workflow, stage)
            for workflow in workflows[:50]
            for stage in workflow["payload"].get("stages", [])
            if stage.get("name") == "verify"
        ]
        evidence_ids = list(
            dict.fromkeys(
                identity for _, stage in checks for identity in stage.get("evidence_ids", [])
            )
        )
        receipts = self.repos.run_event_repo.get_many(owner, evidence_ids[:200])
        verification = []
        for workflow, stage in checks:
            identities = stage.get("evidence_ids", [])
            backed = bool(identities) and all(
                (receipt := receipts.get(identity)) is not None
                and (receipt["agent_id"], receipt["thread_id"], receipt["run_id"])
                == (agent, thread, workflow["run_id"])
                and receipt["kind"] in {"tool", "device", "job", "plan", "dispatch", "interaction"}
                and receipt["status"] == "completed"
                and (
                    receipt["payload"].get("receipt") is None
                    or isinstance(receipt["payload"]["receipt"], dict)
                    and receipt["payload"]["receipt"].get("returncode") in (None, 0)
                )
                and receipt["payload"].get("task_outcome") not in ("failed", "error", "blocked")
                and receipt["payload"].get("name") != "work_step"
                for identity in identities
            )
            verification.append(
                {
                    "status": "passed"
                    if stage.get("status") == "completed" and backed
                    else stage.get("status", "pending"),
                    "receipt_backed": backed,
                    "source_refs": [{"kind": "run", "id": workflow["event_id"]}],
                }
            )
        return {
            "execution_state": state,
            "observation": "stale" if active and not fresh and not live else "current",
            "observed_at": time.time(),
            "active_count": len(active[:200]),
            "truncated": len(active) > 200
            or len(plans) >= 100
            or len(workflows) > 50
            or len(evidence_ids) > 200,
            "plans": plans,
            "verification": verification,
            "verification_passed": sum(check["status"] == "passed" for check in verification),
            "verification_reported": sum(stage.get("status") == "completed" for _, stage in checks),
        }

    def brief(self, owner: int, agent: str, thread: str) -> ConversationBrief:
        row = self.scope(owner, agent, thread)
        meta = self.repos.conversation_metadata_repo.get(thread)
        if meta is None:
            raise OctopError(ErrorCode.NOT_FOUND, "conversation metadata missing")
        data, manual = meta["snapshot"], meta["manual"]
        content = GeneratedBrief.model_validate(
            data.get("brief") or {"one_liner": "", "objective": ""}
        )
        facts = self._facts(owner, agent, thread)
        version = max(
            int(data.get("objective_version", 1)), int(manual.get("objective_version", 1))
        )
        work = (
            manual.get("work_state")
            if manual.get("objective_version", version) == version
            else None
        )
        if work is None:
            # Model prose can suggest blockers; it cannot authoritatively change work state.
            work = "in_progress" if manual.get("objective", content.objective) else "unknown"
        tasks = [task for plan in facts["plans"] for task in plan.get("tasks", [])]
        if (
            work == "in_progress"
            and tasks
            and all(task.get("status") == "completed" for task in tasks)
        ):
            work = "ready_for_review"
        state = facts["execution_state"]
        display = (
            state
            if state in {"waiting_approval", "waiting_user", "running", "unknown"}
            else work
            if work != "unknown"
            else state
        )
        coverage = Coverage.model_validate(data.get("coverage") or {}).model_dump()
        archive_revision = self.archive.store.metadata_revision(thread) if self.archive else 0
        dirty = bool(meta["dirty"] or archive_revision != coverage["archive_revision"])
        coverage["complete"] = coverage["complete"] and not dirty
        pending = self.repos.conversation_metadata_repo.pending(thread)
        fresh = (
            "unavailable"
            if not data
            else "updating"
            if dirty and pending
            else "stale"
            if dirty
            else "partial"
            if not coverage["complete"]
            else "current"
        )
        progress = {
            key: getattr(content, key)
            for key in (
                "stage",
                "completed",
                "in_progress",
                "remaining",
                "blockers",
                "next_actions",
            )
        }
        progress = json.loads(json.dumps(progress, default=lambda value: value.model_dump()))
        progress.update({key: value for key, value in facts.items() if key != "plans"})
        progress.update(
            work_state=work,
            display_state=display,
            reported_plan_completed=sum(t.get("status") == "completed" for t in tasks),
            plan_total=len(tasks),
            plan_refs=[
                {"kind": "plan", "id": p["record_id"], "revision": p["revision"]}
                for p in facts["plans"]
            ],
            acceptance=manual.get("acceptance") if work == "completed" else None,
        )
        return ConversationBrief(
            thread_id=thread,
            revision=meta["revision"],
            objective_version=version,
            title=row.title,
            title_source=row.title_source,
            title_revision=row.title_revision,
            suggested_title=data.get("suggested_title"),
            overview={
                "one_liner": content.one_liner,
                "objective": manual.get("objective", content.objective),
                "scope": manual.get("scope", content.scope),
                "constraints": [x.model_dump() for x in content.constraints],
            },
            progress=progress,
            decisions=content.decisions,
            findings=content.findings,
            artifact_refs=[{"path": a.path, "agent_id": a.agent_id} for a in row.artifacts],
            manual_overrides=manual,
            provenance={
                "freshness": fresh,
                "generated_at": meta["generated_at"],
                "source_revision": meta["source_revision"],
                "generated_source_revision": meta["generated_source_revision"],
                "source_watermarks": {
                    **{
                        k: meta[k]
                        for k in ("message_revision", "activity_revision", "artifact_revision")
                    },
                    "archive_revision": archive_revision,
                },
                "coverage": coverage,
                "effective_model_ref": data.get("effective_model_ref"),
                "prompt_version": data.get("prompt_version", PROMPT_VERSION),
                "visibility_scope": "owner",
                "last_error": meta["last_error"],
                "diagnostic": self.repos.conversation_metadata_repo.last_failure(owner, thread)
                if meta["last_error"]
                else {},
            },
        )

    def window(self, value: str) -> tuple[int, int]:
        try:
            if value not in {"today", "last_7d"} and not value.startswith("range:"):
                raise ValueError("invalid window")
            query = value
            if value == "last_7d":
                today = datetime.fromtimestamp(time.time(), ZoneInfo(self.timezone)).date()
                query = f"range:{today - timedelta(days=6)}:{today}"
            start, end = resolve_usage_window(query, timezone=self.timezone)
            return start, min(end, int(time.time()) + 1)
        except ValueError as exc:
            raise OctopError(ErrorCode.SLASH_BAD_ARGS, "invalid date range") from exc

    def source(self, owner: int, agent: str, thread: str, kind: str, identity: str) -> SourceView:
        self.scope(owner, agent, thread)
        if kind == "message":
            rows = self._source_rows(thread, {identity})
            if rows:
                part, offset = message_source(rows[0], budget=12000)
                return SourceView(
                    kind=kind,
                    id=identity,
                    text=part["text"],
                    details={
                        "role": part["role"],
                        "occurred_at": part["occurred_at"],
                        "partial": bool(offset),
                    },
                )
        elif kind == "event":
            row = self.repos.conversation_metadata_repo.event(thread, identity)
            if row:
                return SourceView(
                    kind=kind, id=identity, text=str(row.get("text") or ""), details=row
                )
        elif kind == "run":
            run = self.repos.run_event_repo.get(owner, identity)
            if run and (run["agent_id"], run["thread_id"]) == (agent, thread):
                return SourceView(
                    kind=kind,
                    id=identity,
                    details={
                        k: run[k] for k in ("kind", "status", "created_at", "updated_at", "run_id")
                    },
                )
        elif kind == "plan":
            for plan in self.repos.workbench_repo.list(owner, agent, thread, "plan"):
                if plan["record_id"] == identity:
                    return SourceView(kind=kind, id=identity, details=plan)
        elif kind in {"invocation", "resource"}:
            table = (
                "collaboration_invocations" if kind == "invocation" else "collaboration_resources"
            )
            values = self.repos.collaboration_repo.references(table, owner, thread, [identity])
            if values:
                return SourceView(
                    kind=kind,
                    id=identity,
                    details={
                        k: v
                        for k, v in values[0].items()
                        if k
                        in {
                            "transport_status",
                            "task_outcome",
                            "version",
                            "path",
                            "name",
                            "created_at",
                            "updated_at",
                        }
                    },
                )
        raise OctopError(ErrorCode.NOT_FOUND, "conversation source unavailable")

    def events(
        self, owner: int, agent: str, thread: str, window: str, cursor: str | None = None
    ) -> EventPage:
        brief = self.brief(owner, agent, thread)
        start, end = self.window(window)
        after: tuple[float, str] | None = None
        if cursor:
            try:
                stamp, identity = json.loads(cursor)
                after = float(stamp), str(identity)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                raise OctopError(ErrorCode.SLASH_BAD_ARGS, "invalid event cursor") from exc
        rows = self.repos.conversation_metadata_repo.events(
            thread, start, end, after=after, limit=101
        )
        items = [
            EventView(
                event_id=r["event_id"],
                kind=r["kind"],
                occurred_at=r["occurred_at"],
                recorded_at=r["recorded_at"],
                text=str(r.get("text") or ""),
                source_refs=r.get("source_refs", []),
                author_kind=r.get("author_kind", "runtime"),
                details={
                    key: value for key, value in r.items() if key not in EventView.model_fields
                },
            )
            for r in rows[:100]
        ]
        next_cursor = (
            json.dumps([rows[99]["occurred_at"], rows[99]["event_id"]]) if len(rows) > 100 else None
        )
        return EventPage(
            events=items,
            next_cursor=next_cursor,
            from_ts=start,
            to_ts=end,
            timezone=self.timezone,
            coverage=Coverage.model_validate(brief.provenance["coverage"]),
        )

    def digest_request(
        self, owner: int, agent: str, thread: str, window: str
    ) -> DigestResult | JobView:
        brief = self.brief(owner, agent, thread)
        start, end = self.window(window)
        meta = self.repos.conversation_metadata_repo.get(thread)
        assert meta is not None
        cfg = self.config(owner)
        # Rounded closed ranges cache exactly; current-day ranges cover this observed second.
        key = hashlib.sha256(
            json.dumps(
                [
                    owner,
                    thread,
                    window,
                    start,
                    meta["source_revision"],
                    meta["revision"],
                    cfg.revision,
                    PROMPT_VERSION,
                ]
            ).encode()
        ).hexdigest()
        cached = self.repos.conversation_metadata_repo.digest(key, thread, by_cache=True)
        if cached:
            return DigestResult.model_validate(cached)
        request = {"window": window, "from_ts": start, "to_ts": end, "cache_key": key}
        if not self.repos.conversation_metadata_repo.events(thread, start, end, limit=1):
            result = DigestResult(
                digest_id=new_ulid(),
                window=window,
                from_ts=start,
                to_ts=end,
                timezone=self.timezone,
                summary="",
                coverage=Coverage.model_validate(brief.provenance["coverage"]),
                source_revision=meta["source_revision"],
                generated_at=time.time(),
                freshness="current" if brief.provenance["coverage"]["complete"] else "partial",
            )
            self.repos.conversation_metadata_repo.save_digest(
                thread, key, meta["source_revision"], result.model_dump()
            )
            return result
        return self.job_view(
            self.repos.conversation_metadata_repo.enqueue(
                owner, agent, thread, "digest", request, f"digest:{key}"
            )
        )

    def digest(self, owner: int, agent: str, thread: str, identity: str) -> DigestResult:
        self.scope(owner, agent, thread)
        data = self.repos.conversation_metadata_repo.digest(identity, thread)
        if not data:
            raise OctopError(ErrorCode.NOT_FOUND, "digest not found")
        meta = self.repos.conversation_metadata_repo.get(thread)
        if meta and meta["source_revision"] != data["source_revision"]:
            data["freshness"] = "stale"
        return DigestResult.model_validate(data)

    async def tick(self) -> None:
        if self.archive:
            for change in await asyncio.to_thread(self.archive.store.metadata_changes):
                await asyncio.to_thread(
                    self.repos.conversation_metadata_repo.archive_changed,
                    change["thread_id"],
                    change["first_seq"],
                )
                await asyncio.to_thread(
                    self.archive.store.acknowledge_metadata, change["thread_id"], change["revision"]
                )
        jobs = []
        for _ in range(4):
            job = await asyncio.to_thread(self.repos.conversation_metadata_repo.claim)
            if job is None:
                break
            jobs.append(job)
        if jobs:
            await asyncio.gather(*(self.process(job) for job in jobs))

    async def process(self, job: dict[str, Any]) -> None:
        owner, agent, thread = job["owner_user_id"], job["agent_id"], job["thread_id"]
        try:
            self.scope(owner, agent, thread)
            cfg = self.config(owner)
            if job["kind"] == "auto" and not (cfg.title_enabled or cfg.brief_enabled):
                self.repos.conversation_metadata_repo.finish(job, "cancelled")
                return
            if job["kind"] == "digest":
                await self._generate_digest(job, cfg)
            else:
                await self._generate_brief(job, cfg)
        except asyncio.CancelledError:
            # Keep the lease for another process to recover after shutdown.
            raise
        except Exception as exc:
            if isinstance(exc, ValueError) and str(exc) == "METADATA_LEASE_LOST":
                return
            retryable = isinstance(exc, (TimeoutError, ConnectionError)) or type(exc).__name__ in {
                "RateLimitError",
                "APIConnectionError",
                "APITimeoutError",
                "InternalServerError",
            }
            code = generation_error_code(exc)
            retry = retryable and job["attempts"] < 3
            delay = 5 if job["attempts"] == 1 else 30
            response = getattr(exc, "response", None)
            retry_after = (getattr(response, "headers", {}) or {}).get("retry-after")
            if retry_after and str(retry_after).isdigit():
                delay = max(delay, int(retry_after))
            self.repos.conversation_metadata_repo.finish(
                job,
                "retry" if retry else "failed",
                error=code,
                delay=delay,
                result={
                    "diagnostic": safe_diagnostics(
                        exc, code=code, stage=job["kind"], job_id=job["job_id"]
                    )
                },
            )
            logger.warning(
                "Conversation metadata generation status=%s exception=%s http_status=%s job=%s",
                code,
                type(exc).__name__,
                getattr(exc, "status_code", None),
                job["job_id"],
            )

    def _chunk(self, thread: str, meta: dict[str, Any]) -> tuple[list[dict[str, Any]], Coverage]:
        previous = meta["snapshot"]
        coverage = Coverage.model_validate(previous.get("coverage") or {})
        seq, offset = coverage.message_seq, coverage.message_offset
        rows = self.repos.conversation_metadata_repo.messages(
            thread, max(0, seq - 1) if offset else seq, limit=80
        )
        messages: list[dict[str, Any]] = []
        budget = 3800
        for row in rows:
            if row["role"] not in {"user", "assistant", "human", "ai"}:
                seq, offset = row["seq"], 0
                continue
            source, partial_offset = message_source(row, offset if row["seq"] == seq else 0, budget)
            if source["text"]:
                messages.append(source)
                budget -= len(json.dumps(source, ensure_ascii=False).encode("utf-8"))
            seq, offset = row["seq"], partial_offset
            if offset or budget < 300:
                break
        complete = not offset and seq >= self.repos.thread_message_repo.head(thread)
        archive_seq, archive_offset = coverage.archive_seq, coverage.archive_offset
        if complete and self.archive and budget > 300:
            archived = self.archive.store.metadata_messages(
                thread,
                max(0, archive_seq - 1) if archive_offset else archive_seq,
                limit=80,
                stable=True,
            )
            for row in archived:
                archive_seq = row["seq"]
                if row["role"] not in {"human", "ai", "user", "assistant"}:
                    archive_offset = 0
                    continue
                source, partial_offset = message_source(row, archive_offset, max(1, budget))
                if source["text"]:
                    messages.append(source)
                    budget -= len(json.dumps(source, ensure_ascii=False).encode("utf-8"))
                archive_offset = partial_offset
                if archive_offset or budget < 300:
                    break
        if self.archive:
            complete = (
                complete
                and not archive_offset
                and archive_seq >= self.archive.store.metadata_head(thread)
            )
        history = self.repos.thread_message_repo.projection_status(thread)
        return messages, Coverage(
            message_seq=seq,
            message_offset=offset,
            archive_seq=archive_seq,
            archive_offset=archive_offset,
            event_seq=coverage.event_seq,
            complete=complete and history == "ready",
            history_status=history,
        )

    async def _call(
        self,
        job: dict[str, Any],
        ref: str | None,
        payload: dict[str, Any],
        schema: dict[str, Any],
        purpose: str,
        valid_refs: set[tuple[str, str]] | None = None,
    ) -> dict[str, Any]:
        if ref is None:
            raise ValueError("METADATA_MODEL_UNAVAILABLE")
        if not self.repos.conversation_metadata_repo.renew(job):
            raise ValueError("METADATA_LEASE_LOST")
        contract = {c.__name__: c for c in (GeneratedTitle, GeneratedBrief, GeneratedDigest)}[
            schema["title"]
        ]
        correction = ""
        for attempt in range(2):
            call_payload = {**payload, **({"format_correction": correction} if correction else {})}
            task = asyncio.create_task(
                generate_json(self.manager, job, ref, call_payload, schema, purpose)
            )
            try:
                while not task.done():
                    await asyncio.wait({task}, timeout=1)
                    if not await asyncio.to_thread(
                        self.repos.conversation_metadata_repo.renew, job
                    ):
                        raise ValueError("METADATA_LEASE_LOST")
                raw = await task
            except ValueError as exc:
                if str(exc) != "METADATA_OUTPUT_TRUNCATED" or attempt:
                    raise
                correction = "The response hit the output token limit. Return a complete JSON object under 900 tokens, omit all optional lists and preserve only essential facts with exact source refs."
                continue
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            try:
                value = output_json(raw)
                parsed = contract.model_validate(value)
                if valid_refs is not None:
                    for items in parsed.model_dump().values():
                        if isinstance(items, list):
                            for item in items:
                                if isinstance(item, dict) and any(
                                    (r["kind"], r["id"]) not in valid_refs
                                    for r in item.get("source_refs", [])
                                ):
                                    raise ValueError("METADATA_INVALID_REFERENCES")
                return value
            except (ValueError, ValidationError) as exc:
                if attempt:
                    raise
                # Retry the same model with original data, never the malformed text
                # or its potentially sensitive validation values.
                paths = (
                    [issue["path"] for issue in output_issues(exc)]
                    if isinstance(exc, ValidationError)
                    else []
                )
                correction = (
                    "Your previous response did not match the schema. Return one complete compact JSON object, no prose or fences. Use objects with text and source_refs for list items, copying kind/id exactly from supplied refs. Omit optional lists rather than inventing sources. Invalid field paths: "
                    + ", ".join(paths)
                )
                logger.info("Retry metadata output format job=%s fields=%s", job["job_id"], paths)
        raise ValueError("METADATA_INVALID_OUTPUT")

    async def _generate_brief(self, job: dict[str, Any], cfg: MetadataSettings) -> None:
        owner, agent, thread = job["owner_user_id"], job["agent_id"], job["thread_id"]
        row = self.scope(owner, agent, thread)
        repo = self.repos.conversation_metadata_repo
        meta = repo.get(thread)
        assert meta is not None
        archive_revision = self.archive.store.metadata_revision(thread) if self.archive else 0
        if (
            job["kind"] == "auto"
            and not meta["dirty"]
            and (row.title_source != "fallback" or not cfg.title_enabled)
        ):
            repo.finish(job, "ready")
            return
        runtime = getattr(self.manager, "_conversation_runtime", {})
        if (
            job["kind"] == "auto"
            and row.title_source == "fallback"
            and runtime.get("turn_active")
            and runtime["turn_active"](thread)
        ):
            repo.finish(job, "queued", delay=5)
            return
        if (
            job["kind"] == "auto"
            and meta["generated_at"]
            and time.time() - meta["generated_at"] < 60
        ):
            repo.finish(job, "queued", delay=max(1, 60 - (time.time() - meta["generated_at"])))
            return
        messages, coverage = await asyncio.to_thread(self._chunk, thread, meta)
        coverage.archive_revision = archive_revision
        previous = meta["snapshot"]
        title_needed = job["kind"] == "title" or (
            job["kind"] in {"auto", "brief"}
            and cfg.title_enabled
            and row.title_source == "fallback"
        )
        brief_needed = job["kind"] == "brief" or (job["kind"] == "auto" and cfg.brief_enabled)
        first_sources = self.repos.conversation_metadata_repo.messages(thread, limit=4)
        if not first_sources and self.archive:
            first_sources = self.archive.store.metadata_messages(thread, limit=4, stable=True)
        title_sources = [
            message_source(r, budget=1200)[0]
            for r in first_sources
            if r["role"] in {"user", "assistant", "human", "ai"}
        ]
        if not title_sources and not messages and not meta["activity_revision"]:
            repo.finish(job, "ready")
            return
        title_model = self.resolve_model(owner, cfg.title_model)
        brief_model = self.resolve_model(owner, cfg.brief_model, cfg.title_model)
        title: str | None = None
        title_error: Exception | None = None
        if title_needed:
            try:
                value = await self._call(
                    job,
                    title_model,
                    {
                        "messages": title_sources,
                        "current_objective": meta["manual"].get("objective")
                        or previous.get("brief", {}).get("objective", ""),
                    },
                    GeneratedTitle.model_json_schema(),
                    "thread_title",
                )
                title = GeneratedTitle.model_validate(value).title
                self.scope(owner, agent, thread)
                if title_model is None or not self.manager.providers_for_user(
                    owner
                ).is_model_ref_usable(title_model):
                    raise ValueError("METADATA_MODEL_UNAVAILABLE")
                if job["kind"] != "title":
                    if (
                        self.archive
                        and self.archive.store.metadata_revision(thread) != archive_revision
                    ):
                        repo.retry_partial(job, 1)
                        return
                    # Commit independently: a later brief failure must not discard a valid title.
                    if not repo.commit(
                        job,
                        source_revision=meta["source_revision"],
                        manual_revision=meta["revision"],
                        config_revision=cfg.revision,
                        title=title,
                        title_revision=row.title_revision,
                    ):
                        repo.retry_partial(job, delay=5)
                        return
                    title = None
                    if self.notify:
                        await self.notify(
                            owner,
                            {
                                "type": "thread_metadata.updated",
                                "agent_id": agent,
                                "thread_id": thread,
                            },
                        )
            except Exception as exc:
                if not brief_needed:
                    raise
                title_error = exc
        snapshot: dict[str, Any] | None = None
        generated_events: list[dict[str, Any]] = []
        if brief_needed:
            # Keep factual events as independent sources, not just the last summary's prose.
            events = repo.source_events(thread, coverage.event_seq, limit=9)
            coverage.complete = coverage.complete and len(events) <= 8
            events = events[:8]
            if events:
                coverage.event_seq = events[-1]["seq"]
            event_sources = [
                {
                    "ref": {"kind": "event", "id": e["event_id"]},
                    "kind": e["kind"],
                    "text": e.get("text", ""),
                    "facts": {
                        k: e[k]
                        for k in ("status", "outcome", "facts", "changes", "tasks")
                        if k in e
                    },
                    "occurred_at": e["occurred_at"],
                }
                for e in events
            ]
            # A bounded prior summary is accompanied by its original cited messages.
            old_brief = previous.get("brief") or {}
            prior_refs = {
                ref["id"]
                for items in old_brief.values()
                if isinstance(items, list)
                for item in items
                if isinstance(item, dict)
                for ref in item.get("source_refs", [])
                if ref.get("kind") == "message"
            }
            prior_rows = self._source_rows(thread, prior_refs)
            originals = [message_source(r, budget=200)[0] for r in prior_rows[:12]]
            prior_events = {
                ref["id"]
                for items in old_brief.values()
                if isinstance(items, list)
                for item in items
                if isinstance(item, dict)
                for ref in item.get("source_refs", [])
                if ref.get("kind") == "event"
            }
            retained_events = [
                prior_event
                for identity in prior_events
                if (prior_event := repo.event(thread, identity))
            ]
            valid_refs = {
                (s["ref"]["kind"], s["ref"]["id"]) for s in [*messages, *originals, *event_sources]
            }
            valid_refs.update(("message", str(r.get("ref_id") or r["seq"])) for r in prior_rows)
            valid_refs.update(("event", e["event_id"]) for e in retained_events)
            payload = {
                "messages": messages,
                "previous": old_brief,
                "original_sources": originals,
                "events": event_sources,
                "user_overrides": meta["manual"],
                "coverage": coverage.model_dump(),
            }
            value = await self._call(
                job,
                brief_model,
                payload,
                GeneratedBrief.model_json_schema(),
                "thread_brief",
                valid_refs,
            )
            content = GeneratedBrief.model_validate(value)
            for name in (
                "constraints",
                "completed",
                "in_progress",
                "remaining",
                "blockers",
                "next_actions",
                "decisions",
                "findings",
                "events",
            ):
                for item in getattr(content, name):
                    if any((ref.kind, ref.id) not in valid_refs for ref in item.source_refs):
                        raise ValueError("METADATA_INVALID_OUTPUT")
            version = max(
                int(previous.get("objective_version", 1)),
                int(meta["manual"].get("objective_version", 1)),
            )
            if (
                previous
                and content.new_objective
                and any(s["role"] == "user" for s in messages)
                and content.objective != old_brief.get("objective")
            ):
                version += 1
            times = {
                (s["ref"]["kind"], s["ref"]["id"]): s["occurred_at"]
                for s in [*messages, *originals, *event_sources]
            }
            times.update(
                (
                    ("message", str(r.get("ref_id") or r["seq"])),
                    message_source(r, budget=1)[0]["occurred_at"],
                )
                for r in prior_rows
            )
            times.update((("event", e["event_id"]), e["occurred_at"]) for e in retained_events)
            for event in content.events:
                refs = [r.model_dump(exclude_none=True) for r in event.source_refs]
                source = hashlib.sha256(
                    json.dumps([event.kind, refs], sort_keys=True).encode()
                ).hexdigest()[:24]
                generated_events.append(
                    {
                        "source_key": f"semantic:{source}",
                        "kind": event.kind,
                        "occurred_at": max(times[(r.kind, r.id)] for r in event.source_refs),
                        "payload": {
                            "text": event.text,
                            "source_refs": refs,
                            "author_kind": "model",
                        },
                    }
                )
            snapshot = {
                "brief": content.model_dump(),
                "coverage": coverage.model_dump(),
                "effective_model_ref": brief_model,
                "objective_version": version,
                "prompt_version": PROMPT_VERSION,
                "suggested_title": previous.get("suggested_title"),
            }
            if (
                version > int(previous.get("objective_version", 1))
                and cfg.title_enabled
                and row.title_source == "automatic"
            ):
                try:
                    candidate = await self._call(
                        job,
                        title_model,
                        {"messages": messages, "objective": content.objective},
                        GeneratedTitle.model_json_schema(),
                        "thread_title",
                    )
                    snapshot["suggested_title"] = GeneratedTitle.model_validate(candidate).title
                except Exception:
                    logger.warning(
                        "Conversation title suggestion unavailable job=%s", job["job_id"]
                    )
        # Permission/model/config changes during a call may invalidate a result.
        self.scope(owner, agent, thread)
        if self.archive and self.archive.store.metadata_revision(thread) != archive_revision:
            repo.retry_partial(job, 1)
            return
        for ref in {
            brief_model if brief_needed else None,
        } - {None}:
            if not self.manager.providers_for_user(owner).is_model_ref_usable(ref):
                raise ValueError("METADATA_MODEL_UNAVAILABLE")
        if job["kind"] == "title":
            if self.config(owner).revision != cfg.revision:
                repo.retry_partial(job, 1)
                return
            repo.finish(
                job, "ready", {"suggested_title": title, "title_revision": row.title_revision}
            )
            return
        committed = repo.commit(
            job,
            source_revision=meta["source_revision"],
            manual_revision=meta["revision"],
            config_revision=cfg.revision,
            snapshot=snapshot,
            title=title,
            title_revision=row.title_revision,
            events=generated_events,
            complete=coverage.complete,
        )
        if not committed:
            repo.retry_partial(job, delay=5)
            return
        if title_error is not None:
            raise title_error
        if brief_needed and not coverage.complete and coverage.history_status == "ready":
            repo.retry_partial(job, delay=1)
        else:
            repo.finish(job, "ready", {"thread_id": thread})
        if self.notify:
            await self.notify(
                owner, {"type": "thread_metadata.updated", "agent_id": agent, "thread_id": thread}
            )

    async def _generate_digest(self, job: dict[str, Any], cfg: MetadataSettings) -> None:
        owner, agent, thread = job["owner_user_id"], job["agent_id"], job["thread_id"]
        repo = self.repos.conversation_metadata_repo
        brief = self.brief(owner, agent, thread)
        request = job["request"]
        progress = request.get("progress") or {
            "source_revision": brief.provenance["source_revision"],
            "config_revision": cfg.revision,
            "coverage": brief.provenance["coverage"],
            "archive_revision": brief.provenance["source_watermarks"]["archive_revision"],
            "summary": "",
            "event_ids": [],
            "after": None,
            "chunks": 0,
        }
        if progress["config_revision"] != cfg.revision:
            repo.finish(job, "cancelled", error="METADATA_CONFIGURATION_CHANGED")
            return
        after = tuple(progress["after"]) if progress["after"] else None
        model = self.resolve_model(owner, cfg.brief_model, cfg.title_model)
        # Persist each reduction step. The next page retries independently after a crash.
        rows = repo.events(thread, request["from_ts"], request["to_ts"], after=after, limit=9)
        more, rows = len(rows) > 8, rows[:8]
        if rows:
            public = []
            truncated = False
            for row in rows:
                text = json.dumps(
                    {
                        k: row[k]
                        for k in ("text", "status", "outcome", "facts", "changes", "tasks")
                        if k in row
                    },
                    ensure_ascii=False,
                )
                bounded = text.encode("utf-8")[:400].decode("utf-8", errors="ignore")
                truncated = truncated or bounded != text
                public.append(
                    {
                        "event_id": row["event_id"],
                        "occurred_at": row["occurred_at"],
                        "kind": row["kind"],
                        "data": bounded,
                        "partial": bounded != text,
                    }
                )
            value = await self._call(
                job,
                model,
                {
                    "range": {k: request[k] for k in ("window", "from_ts", "to_ts")},
                    "events": public,
                    "previous_summary": progress["summary"],
                    "instruction": "Merge this page into previous_summary, preserving unresolved work, corrections and earlier milestones. Keep the merged summary under 1000 characters. event_ids must cite only the current page; prior page references are retained separately. Do not infer later outcomes.",
                },
                GeneratedDigest.model_json_schema(),
                "thread_digest",
            )
            generated = GeneratedDigest.model_validate(value)
            valid = {r["event_id"] for r in rows}
            if any(identity not in valid for identity in generated.event_ids):
                raise ValueError("METADATA_INVALID_OUTPUT")
            progress.update(
                summary=generated.summary,
                after=[rows[-1]["occurred_at"], rows[-1]["event_id"]],
                chunks=progress["chunks"] + 1,
            )
            # Every processed event remains inspectable, including events compressed out of prose.
            progress["event_ids"] = list(
                dict.fromkeys([*progress["event_ids"], *(r["event_id"] for r in rows)])
            )
            if truncated:
                progress["coverage"].update(truncated_sources=True, complete=False)
            if not repo.checkpoint(job, {**request, "progress": progress}):
                return
            if more:
                repo.retry_partial(job, 1)
                return
        current = self.brief(owner, agent, thread)
        if self.config(owner).revision != cfg.revision:
            repo.finish(job, "cancelled", error="METADATA_CONFIGURATION_CHANGED")
            return
        if model is None or not self.manager.providers_for_user(owner).is_model_ref_usable(model):
            raise ValueError("METADATA_MODEL_UNAVAILABLE")
        result = DigestResult(
            digest_id=new_ulid(),
            window=request["window"],
            from_ts=request["from_ts"],
            to_ts=request["to_ts"],
            timezone=self.timezone,
            summary=progress["summary"],
            event_ids=progress["event_ids"],
            coverage=Coverage.model_validate(progress["coverage"]),
            source_revision=progress["source_revision"],
            generated_at=time.time(),
            effective_model_ref=model,
            freshness="stale"
            if (
                current.provenance["source_revision"] != progress["source_revision"]
                or current.provenance["source_watermarks"]["archive_revision"]
                != progress["archive_revision"]
            )
            else "current"
            if progress["coverage"]["complete"]
            else "partial",
        )
        self.scope(owner, agent, thread)
        if repo.save_digest(
            thread,
            request["cache_key"],
            result.source_revision,
            result.model_dump(),
            job=job,
            config_revision=cfg.revision,
        ):
            stored = repo.digest(request["cache_key"], thread, by_cache=True)
            assert stored is not None
            repo.finish(job, "ready", {"digest_id": stored["digest_id"]})
