"""CronJob — APScheduler callable with status and audit bookkeeping."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from octop.i18n.domains.stream import format_stream_error
from octop.infra.cron.delivery import CronDeliveryCommand
from octop.infra.cron.report import ReportOptions, report_options
from octop.infra.cron.task_type import normalize_cron_task_type
from octop.infra.db.repos.audit import ACTOR_SYSTEM

if TYPE_CHECKING:
    from octop.infra.cron.delivery import CronDeliveryService
    from octop.infra.db.repos.audit import AuditRepo
    from octop.infra.db.repos.cron import CronJobRepo, CronJobRow

logger = logging.getLogger(__name__)


class CronJob:
    def __init__(
        self,
        *,
        cron_id: str,
        name: str,
        agent_id: str,
        prompt: str,
        fresh_thread: bool,
        session_key: str,
        model: str | None,
        task_type: str,
        mcp_servers: list[str] | None,
        user_id: int,
        delivery_service: CronDeliveryService,
        cron_repo: CronJobRepo,
        audit_repo: AuditRepo,
        report: ReportOptions | None = None,
        report_origin_session: str = "",
    ) -> None:
        self._cron_id = cron_id
        self._name = name
        self._agent_id = agent_id
        self._prompt = prompt
        self._fresh_thread = fresh_thread
        self._session_key = session_key
        self._model = model
        self._task_type = normalize_cron_task_type(task_type)
        self._mcp_servers = list(mcp_servers or [])
        self._user_id = user_id
        self._delivery_service = delivery_service
        self._cron_repo = cron_repo
        self._audit_repo = audit_repo
        self._report = report
        self._report_origin_session = report_origin_session

    @classmethod
    def from_row(
        cls,
        row: CronJobRow,
        *,
        delivery_service: CronDeliveryService,
        cron_repo: CronJobRepo,
        audit_repo: AuditRepo,
    ) -> CronJob:
        return cls(
            cron_id=row.cron_id,
            name=row.name,
            agent_id=row.agent_id,
            prompt=row.prompt,
            fresh_thread=bool(row.fresh_thread),
            session_key=row.session_key,
            model=row.model,
            task_type=row.task_type,
            mcp_servers=list(row.mcp_servers),
            user_id=row.user_id,
            delivery_service=delivery_service,
            cron_repo=cron_repo,
            audit_repo=audit_repo,
            report=report_options(row),
            report_origin_session=str((row.meta or {}).get("previous_session_key") or ""),
        )

    async def run(self, *, raise_on_error: bool = False, reason: str = "timer") -> None:
        from octop.infra.metrics import METRICS  # noqa: PLC0415

        METRICS.inc("cron_runs_total")
        ts = int(time.time())

        try:
            row = self._cron_repo.get(self._cron_id)
            if row is None or (not row.enabled and reason != "manual"):
                return
            if (report_options(row) is not None) != (self._report is not None):
                return
            from octop.infra.cron.self_reminder import is_self_reminder_row

            command = CronDeliveryCommand(
                cron_id=self._cron_id,
                reason=reason,
                cron_name=self._name,
                agent_id=self._agent_id,
                user_id=self._user_id,
                session_key=self._session_key,
                prompt=self._prompt,
                fresh_thread=self._fresh_thread and not is_self_reminder_row(row),
                task_type=self._task_type,
                model=self._model,
                mcp_servers=tuple(self._mcp_servers),
                report=self._report,
                report_origin_session=self._report_origin_session,
            )
            await self._delivery_service.deliver(command)
        except Exception as exc:
            METRICS.inc("cron_errors_total")
            logger.exception("cron job %s failed", self._cron_id)
            err = format_stream_error(exc, "en")
            self._cron_repo.set_run_status(self._cron_id, ts=ts, status="error", error=err)
            self._audit_repo.write(
                actor=ACTOR_SYSTEM,
                action="cron.run_failed",
                target=self._cron_id,
                payload=err,
            )
            if raise_on_error:
                raise
            return
        self._cron_repo.set_run_status(self._cron_id, ts=ts, status="ok", error=None)
        self._audit_repo.write(
            actor=ACTOR_SYSTEM,
            action="cron.run_ok",
            target=self._cron_id,
        )
        self._maybe_consume_self_reminder()

    def _maybe_consume_self_reminder(self) -> None:
        """Disable one-shot self-reminders; honor max_fires for interval repeats."""
        row = self._cron_repo.get(self._cron_id)
        if row is None:
            return
        from octop.infra.cron.self_reminder import MAX_FIRES_HARD_CAP, is_self_reminder_row

        if not is_self_reminder_row(row):
            return
        meta = dict(row.meta or {})
        fires = int(meta.get("fires") or 0) + 1
        max_fires = int(meta.get("max_fires") or 1)
        max_fires = max(1, min(max_fires, MAX_FIRES_HARD_CAP))
        meta["fires"] = fires
        self._cron_repo.set_meta(self._cron_id, meta)
        if fires >= max_fires:
            self._cron_repo.update(self._cron_id, enabled=False)
