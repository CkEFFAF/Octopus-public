"""Cron delivery orchestration, separate from channel transport."""

from __future__ import annotations

import asyncio
import logging
import weakref
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage

from octop.i18n import tr
from octop.i18n.domains.stream import format_stream_error
from octop.infra.cron.report import ReportOptions, report_options
from octop.infra.cron.task_type import CronTaskType, normalize_cron_task_type
from octop.infra.gateway.process import build_harness_request
from octop.infra.gateway.process.message_keys import COMPOSER_CTX_KEY, build_composer_context
from octop.infra.gateway.process.usage_record import UsageTracker, record_turn_usage
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.history.projection import TurnHistoryTracker, message_inputs
from octop.infra.knowledge.default_open import stamp_turn_knowledge_config
from octop.infra.utils.llm_text import strip_thinking
from octop.infra.utils.locale import resolve_user_locale
from octop.infra.utils.ulid import new_ulid

if TYPE_CHECKING:
    from octop.infra.agents.manager import AgentManager
    from octop.infra.db.repos.sessions import SessionRow
    from octop.infra.db.repos.thread_messages import ThreadMessageInput
    from octop.infra.db.services import RepoBundle
    from octop.infra.gateway.gateway import Gateway

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CronDeliveryCommand:
    """Immutable inputs for one scheduled delivery attempt."""

    cron_id: str
    cron_name: str
    agent_id: str
    user_id: int
    session_key: str
    prompt: str
    fresh_thread: bool
    task_type: CronTaskType
    model: str | None
    mcp_servers: tuple[str, ...]
    device_id: str = ""
    device_grant_version: int = 0
    task_run_id: str = ""
    reason: str = "timer"
    report: ReportOptions | None = None
    report_origin_session: str = ""


class CronDeliveryService:
    """Persist canonical cron turns and deliver their visible output."""

    def __init__(
        self,
        *,
        gateway: Gateway,
        agent_manager: AgentManager,
        repos: RepoBundle,
    ) -> None:
        self._gateway = gateway
        self._agent_manager = agent_manager
        self._repos = repos
        self._report_locks: weakref.WeakValueDictionary[tuple[int, str, str], asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )

    def replace_repos(self, repos: RepoBundle) -> None:
        """Retarget projection and locale lookups after a control-plane swap."""
        self._repos = repos

    async def deliver(self, command: CronDeliveryCommand) -> str:
        """Run one delivery under the target channel session lock."""
        if command.report is None:
            return await self._deliver(command)
        key = (command.user_id, command.agent_id, command.cron_id)
        lock = self._report_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._report_locks[key] = lock
        async with lock:
            await self.cleanup_report_executions(command.user_id, command.agent_id, command.cron_id)
            try:
                return await self._deliver(command)
            finally:
                await self.cleanup_report_executions(
                    command.user_id, command.agent_id, command.cron_id
                )

    async def _deliver(self, command: CronDeliveryCommand) -> str:

        output = ""
        attempt = new_ulid()
        source = self._repos.session_repo.get(command.session_key)
        source_thread = (
            source.thread_id
            if source and (source.user_id, source.agent_id) == (command.user_id, command.agent_id)
            else None
        )
        attempts = self._repos.cron_attempt_repo
        attempts.create(
            attempt,
            command.user_id,
            command.agent_id,
            command.cron_id,
            source_thread,
            command.reason,
        )
        command = replace(
            command,
            task_run_id=(command.task_run_id or new_ulid()) if command.task_type == "agent" else "",
        )

        async def _locked() -> None:
            nonlocal output
            original = self._gateway.require_session(command.agent_id, command.session_key)
            if (original.user_id, original.agent_id) != (command.user_id, command.agent_id):
                raise ValueError("cron session does not belong to user or agent (mismatch)")
            if command.fresh_thread:
                reset = True
                if command.report is not None:
                    thread = await asyncio.to_thread(
                        self._repos.thread_repo.get, original.thread_id
                    )
                    recent = (
                        await asyncio.to_thread(
                            attempts.listing,
                            command.user_id,
                            command.agent_id,
                            command.cron_id,
                            limit=2,
                        )
                    )["items"]
                    already_used = any(
                        item["attempt_id"] != attempt
                        and item["actual_thread_id"] == original.thread_id
                        for item in recent
                    )
                    reset = thread is None or thread.last_active != 0 or already_used
                if reset:
                    await self._gateway.thread_registry.reset_by_session_key(command.session_key)
            session = self._gateway.require_session(command.agent_id, command.session_key)
            if session.user_id != command.user_id:
                raise ValueError(
                    f"session {command.session_key!r} does not belong to user {command.user_id!r}"
                )
            if session.agent_id != command.agent_id:
                raise ValueError("cron session agent mismatch")
            if command.report is not None and session.thread_id != original.thread_id:
                await self.inherit_report_target(
                    command.user_id, original.thread_id, session.thread_id
                )
            attempts.update(
                command.user_id,
                attempt,
                "running",
                thread=session.thread_id,
                run=command.task_run_id or None,
            )
            if command.task_type == "text":
                await self._deliver_text(command, session)
                output = command.prompt
            else:
                output = await self._deliver_agent(command, session, attempt=attempt)
                if command.report is not None:
                    await asyncio.to_thread(
                        self._repos.cron_report_repo.save,
                        attempt=attempt,
                        owner=command.user_id,
                        agent=command.agent_id,
                        cron=command.cron_id,
                        thread=session.thread_id,
                        output=output,
                    )

        try:
            await self._gateway.run_in_session(command.agent_id, command.session_key, _locked)
        except asyncio.CancelledError:
            attempts.update(
                command.user_id, attempt, "cancelled", error="Scheduled delivery was cancelled"
            )
            raise
        except Exception as exc:
            # Transport exceptions may contain provider URLs, headers or credentials.
            attempts.update(
                command.user_id,
                attempt,
                "failed",
                error=f"Scheduled delivery failed ({type(exc).__name__})",
            )
            raise
        attempts.update(
            command.user_id,
            attempt,
            "delivered" if command.task_type == "text" else "completed",
            result=output[:2000],
        )
        return output

    async def recover_report_executions(self) -> None:
        scopes = await asyncio.to_thread(self._repos.cron_attempt_repo.report_cleanup_scopes)
        for scope in scopes:
            await self.cleanup_report_executions(
                scope["owner_user_id"], scope["agent_id"], scope["cron_id"]
            )

    async def cleanup_report_executions(self, owner: int, agent: str, cron: str) -> None:
        from octop.infra.agents.threads.fork import load_checkpoint_messages

        candidates = await asyncio.to_thread(
            self._repos.cron_attempt_repo.report_cleanup_candidates, owner, agent, cron
        )
        for item in candidates:
            thread = item["execution_thread_id"]
            try:
                harness = self._agent_manager.get_agent(agent)
                messages = await load_checkpoint_messages(harness, thread)
                await asyncio.to_thread(
                    self._repos.thread_message_repo.append_if_ready,
                    thread,
                    message_inputs(messages, dedupe_missing_ids=True),
                )
                deleted = await self._agent_manager.delete_thread_checkpoint(agent, thread)
                if deleted or not messages:
                    await asyncio.to_thread(
                        self._repos.cron_attempt_repo.report_cleanup_done, owner, item["attempt_id"]
                    )
            except Exception:
                logger.warning("scheduled report checkpoint cleanup will be retried", exc_info=True)

    async def _deliver_text(
        self,
        command: CronDeliveryCommand,
        session: SessionRow,
    ) -> None:
        projected: list[ThreadMessageInput] = []
        title_source = command.prompt
        if session.channel_type == ThreadRegistry.CHANNEL_DASHBOARD:
            delivery_id = new_ulid()
            locale = resolve_user_locale(
                user_repo=self._repos.user_repo,
                user_id=session.user_id,
                channel_type=session.channel_type,
            )
            human_text = tr(
                "cron.history.executed",
                locale,
                cron_id=command.cron_id,
                name=command.cron_name,
            )
            title_source = human_text
            canonical = [
                HumanMessage(
                    content=human_text,
                    id=f"cron:{delivery_id}:human",
                ),
                AIMessage(
                    content=command.prompt,
                    id=f"cron:{delivery_id}:assistant",
                ),
            ]
            harness = self._agent_manager.get_agent(command.agent_id)
            appended = await harness.aappend_messages(session.thread_id, canonical)
            projected = message_inputs(appended, dedupe_missing_ids=True)

        self._project_best_effort(session.thread_id, projected)
        await self._gateway.push_session_text(
            session,
            command.prompt,
            title_source=title_source,
        )
        await self._notify_best_effort(session, command.agent_id, command.prompt)

    async def _deliver_agent(
        self,
        command: CronDeliveryCommand,
        session: SessionRow,
        *,
        attempt: str = "",
    ) -> str:
        request = await self._build_agent_request(command, session)
        execution_thread = ""
        if command.report is not None:
            execution_thread = f"cron-report-execution-{attempt}"
            await asyncio.to_thread(
                self._repos.thread_repo.insert,
                thread_id=execution_thread,
                agent_id=command.agent_id,
                user_id=command.user_id,
                channel_type="cron_internal",
                session_key=command.session_key,
                last_active=0,
            )
            await asyncio.to_thread(
                self._repos.cron_attempt_repo.bind_report_execution,
                command.user_id,
                attempt,
                execution_thread,
            )
            await self.inherit_report_target(command.user_id, session.thread_id, execution_thread)
            request["thread_id"] = execution_thread
            if command.report.include_previous:
                prior_reports = await asyncio.to_thread(
                    self._repos.cron_report_repo.recent,
                    owner=command.user_id,
                    agent=command.agent_id,
                    cron=command.cron_id,
                    limit=command.report.previous_count,
                )
                if prior_reports:
                    locale = resolve_user_locale(
                        user_repo=self._repos.user_repo,
                        user_id=session.user_id,
                        channel_type=session.channel_type,
                    )
                    history: list[Any] = []
                    for report in prior_reports:
                        history.extend(
                            [
                                HumanMessage(content=tr("cron.history.previous_report", locale)),
                                AIMessage(content=report),
                            ]
                        )
                    request["messages"] = history + request["messages"]
        tracker = TurnHistoryTracker.from_request(request)
        usage = UsageTracker()
        parts: list[str] = []
        interaction_required = False
        dashboard = session.channel_type == ThreadRegistry.CHANNEL_DASHBOARD
        run_id = ""
        terminal_seen = False
        fallback_phase = "failed"
        try:
            from octop.infra.connectors.gateway.adapters.agently_cli import write_scope

            with write_scope(allowed=False):
                async for chunk in self._agent_manager.stream(command.agent_id, request):
                    tracker.observe(chunk)
                    usage.observe(chunk)
                    kind = chunk.get("type")
                    if (
                        dashboard
                        and kind in {"run_phase", "steering_applied", "user"}
                        and not (command.report is not None and kind == "user")
                    ):
                        if kind == "run_phase":
                            run_id = str(chunk.get("run_id") or run_id)
                            terminal_seen = chunk.get("phase") in {
                                "completed",
                                "failed",
                                "cancelled",
                                "paused",
                            }
                        elif kind == "steering_applied":
                            # The scheduled turn buffers public output. Preserve
                            # its prior assistant text before the inserted user,
                            # then deliver only the new answer at completion.
                            prior = strip_thinking("".join(parts)).strip()
                            if prior:
                                await self._gateway.observe_dashboard_resume(
                                    session.user_id,
                                    command.agent_id,
                                    session.thread_id,
                                    {"type": "token", "content": prior},
                                )
                            parts.clear()
                        await self._gateway.observe_dashboard_resume(
                            session.user_id,
                            command.agent_id,
                            session.thread_id,
                            chunk,
                        )
                    if chunk.get("type") in ("token", "delta"):
                        parts.append(str(chunk.get("content") or chunk.get("text") or ""))
                    elif chunk.get("type") == "hitl_required":
                        interaction_required = True
            if interaction_required:
                raise RuntimeError("cron agent run requires user interaction")
            outbound = strip_thinking("".join(parts)).strip()
            if not outbound:
                raise RuntimeError("cron agent run produced no visible response")
            fallback_phase = "completed"
        except asyncio.CancelledError:
            fallback_phase = "cancelled"
            raise
        except Exception as exc:
            if dashboard:
                locale = resolve_user_locale(
                    user_repo=self._repos.user_repo,
                    user_id=session.user_id,
                    channel_type=session.channel_type,
                )
                await self._gateway.observe_dashboard_resume(
                    session.user_id,
                    command.agent_id,
                    session.thread_id,
                    {"type": "error", "message": format_stream_error(exc, locale)},
                )
            raise
        finally:
            # ``fresh_thread`` already put an empty thread on the session, so a run
            # that raised before this left a conversation with no rows at all.
            if command.report is None:
                self._project_best_effort(session.thread_id, tracker.inputs)
            if dashboard:
                if run_id and not terminal_seen:
                    await self._gateway.observe_dashboard_resume(
                        session.user_id,
                        command.agent_id,
                        session.thread_id,
                        {"type": "run_phase", "run_id": run_id, "phase": fallback_phase},
                    )
                await self._gateway.observe_dashboard_resume(
                    session.user_id,
                    command.agent_id,
                    session.thread_id,
                    {"type": "done"},
                )
        if command.report is not None:
            harness = self._agent_manager.get_agent(command.agent_id)
            execution_row = await asyncio.to_thread(self._repos.thread_repo.get, execution_thread)
            if execution_row is not None:
                for artifact in execution_row.artifacts:
                    await asyncio.to_thread(
                        self._repos.thread_repo.append_artifacts,
                        session.thread_id,
                        [artifact.path],
                        agent_id=artifact.agent_id,
                    )
            canonical = [
                HumanMessage(content=command.prompt, id=f"cron:{attempt}:human"),
                AIMessage(content=outbound, id=f"cron:{attempt}:assistant"),
            ]
            appended = await harness.aappend_messages(session.thread_id, canonical)
            self._project_best_effort(
                session.thread_id, message_inputs(appended, dedupe_missing_ids=True)
            )
        if usage.usage is not None:
            record_turn_usage(
                self._repos.usage_repo,
                agent_id=command.agent_id,
                user_id=session.user_id,
                thread_id=session.thread_id,
                usage=usage.usage,
                source="cron",
            )
        await self._gateway.push_session_text(
            session,
            outbound,
            title_source=command.cron_name if command.report is not None else command.prompt,
        )
        await self._notify_best_effort(session, command.agent_id, outbound)
        if command.report is not None and command.report_origin_session:
            original = await asyncio.to_thread(
                self._repos.session_repo.get, command.report_origin_session
            )
            if (
                original is not None
                and (original.user_id, original.agent_id) == (command.user_id, command.agent_id)
                and ThreadRegistry.is_im_session(original)
            ):
                await self._gateway.push_session_text(
                    original, outbound, title_source=command.cron_name
                )
        return outbound

    async def inherit_report_target(self, owner: int, source: str, target: str) -> None:
        """Carry a selected execution target across the report's isolated threads."""
        device_service = getattr(self._agent_manager, "_device_service", None)
        if device_service is None:
            return
        from octop.infra.execution.service import ExecutionService

        execution = ExecutionService(device_service)
        source_row = await asyncio.to_thread(self._repos.thread_repo.get, source)
        target_row = await asyncio.to_thread(self._repos.thread_repo.get, target)
        if (
            source_row is None
            or target_row is None
            or (source_row.user_id, source_row.agent_id) != (owner, target_row.agent_id)
            or target_row.user_id != owner
        ):
            raise ValueError("report target inheritance requires matching thread ownership")
        selection = await asyncio.to_thread(execution.selection, owner, source)
        if execution.has_target(selection) or selection.get("work_mode") != "agentic":
            await asyncio.to_thread(execution.save_selection, owner, target, selection)

    async def _build_agent_request(
        self,
        command: CronDeliveryCommand,
        session: SessionRow,
    ) -> dict[str, Any]:
        from octop.infra.agents.teams import is_team_agent

        if is_team_agent(self._agent_manager.get_row(command.agent_id)):
            servers: list[str] = []
        else:
            servers = [name.strip() for name in command.mcp_servers if name.strip()]
            extra_defaults = self._agent_manager.default_mcp_servers(command.agent_id)
            pack = self._agent_manager.device_mcp_pack_for_turn(
                session.user_id,
                agent_id=command.agent_id,
            )
            device_defaults: list[str] = []
            deny_mcp: list[str] = []
            if isinstance(pack, tuple) and len(pack) >= 2:
                device_defaults = list(pack[0] or [])
                deny_mcp = list(pack[1] or [])
            if servers:
                # Explicit cron picks opt out of account+device defaults (same as
                # Dashboard) but device deny still filters the explicit list (DEC-C05).
                servers = (
                    self._agent_manager.merge_turn_mcp_servers(
                        session.user_id,
                        servers,
                        apply_defaults=False,
                        extra_defaults=extra_defaults,
                        deny_mcp_servers=deny_mcp or None,
                    )
                    or []
                )
            else:
                servers = (
                    self._agent_manager.merge_turn_mcp_servers(
                        session.user_id,
                        None,
                        apply_defaults=True,
                        extra_defaults=extra_defaults,
                        device_defaults=device_defaults or None,
                        deny_mcp_servers=deny_mcp or None,
                    )
                    or []
                )
        if servers:
            failed = await self._agent_manager.prepare_chat_mcp(
                command.agent_id,
                servers,
                connector_user_id=session.user_id,
            )
            if failed:
                raise RuntimeError(f"mcp load failed: {', '.join(failed)}")

        row = self._agent_manager.get_row(command.agent_id)
        default_model = (row.default_model if row is not None else None) or None
        composer = build_composer_context(
            mcp_servers=servers or None,
            skills=None,
            target_agent_ids=None,
            model_ref=command.model,
            default_model=default_model,
        )
        message_kwargs = {COMPOSER_CTX_KEY: composer} if composer else None
        request = build_harness_request(
            thread_id=session.thread_id,
            user_id=session.user_id,
            agent_id=command.agent_id,
            session_key=command.session_key,
            source=session.channel_type,
            text=command.prompt,
            model=command.model,
            message_kwargs=message_kwargs,
        )
        if servers:
            request["mcp_servers"] = servers
        if command.device_id:
            request.setdefault("configurable", {})["octop_device_target"] = {
                "device_id": command.device_id,
                "grant_version": command.device_grant_version,
            }
        if command.task_run_id:
            request.setdefault("configurable", {})["octop_task_run_id"] = command.task_run_id
        self._attach_turn_knowledge_config(request, command, session)
        return request

    def _attach_turn_knowledge_config(
        self,
        request: dict[str, Any],
        command: CronDeliveryCommand,
        session: SessionRow,
    ) -> None:
        user_row = self._repos.user_repo.get(session.user_id)
        is_admin = str(getattr(user_row, "role", "") or "") == "admin"
        knowledge_repo = self._repos.knowledge_repo
        bases = (
            knowledge_repo.list_all() if is_admin else knowledge_repo.list_visible(session.user_id)
        )
        locale = resolve_user_locale(
            user_repo=self._repos.user_repo,
            user_id=session.user_id,
            channel_type=session.channel_type,
        )
        stamp_turn_knowledge_config(
            request,
            visible_bases=bases,
            explicit_ids=None,
            owner_user_id=session.user_id,
            extra_ids=self._agent_manager.default_knowledge_base_ids(command.agent_id),
            is_admin=is_admin,
            locale=locale,
        )

    def _project_best_effort(
        self,
        thread_id: str,
        messages: list[ThreadMessageInput],
    ) -> None:
        if not messages:
            return
        try:
            self._repos.thread_message_repo.append_if_ready(thread_id, messages)
        except Exception:
            logger.warning(
                "failed to append cron history projection for thread=%s",
                thread_id,
                exc_info=True,
            )

    async def _notify_best_effort(
        self,
        session: SessionRow,
        agent_id: str,
        text: str,
    ) -> None:
        if session.channel_type != ThreadRegistry.CHANNEL_DASHBOARD:
            return
        try:
            await self._gateway.notify_dashboard_push(session, agent_id, text)
        except Exception:
            logger.warning(
                "failed to send cron dashboard notification for thread=%s",
                session.thread_id,
                exc_info=True,
            )


def command_from_row(row: Any) -> CronDeliveryCommand:
    """Build a delivery command from a persisted cron row."""
    from octop.infra.cron.self_reminder import is_self_reminder_row

    fresh = bool(row.fresh_thread)
    if is_self_reminder_row(row):
        # DEC-002: self-reminders always continue the same session thought chain.
        # Gateway run_in_session already serializes behind a running turn (pending queue).
        fresh = False
    return CronDeliveryCommand(
        cron_id=str(row.cron_id),
        cron_name=str(row.name),
        agent_id=str(row.agent_id),
        user_id=int(row.user_id),
        session_key=str(row.session_key),
        prompt=str(row.prompt),
        fresh_thread=fresh,
        task_type=normalize_cron_task_type(str(row.task_type)),
        model=str(row.model) if row.model else None,
        mcp_servers=tuple(str(name) for name in row.mcp_servers),
        report=report_options(row),
        report_origin_session=str(
            (getattr(row, "meta", None) or {}).get("previous_session_key") or ""
        ),
    )


__all__ = [
    "CronDeliveryCommand",
    "CronDeliveryService",
    "command_from_row",
]
