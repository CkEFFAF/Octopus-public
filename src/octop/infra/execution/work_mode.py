"""Persistent mode stages, receipt-backed evidence and human decision handoffs."""

from __future__ import annotations

import json
import time
from copy import deepcopy
from typing import Any

from langchain_core.tools import tool
from langgraph.config import get_config
from octop_harness.middleware.pii import detect_pii

from octop.infra.db.repos.run_events import RunEventRepo
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError

STAGES: dict[str, tuple[str, ...]] = {
    "agentic": ("execute", "verify"),
    "ask": ("answer",),
    "plan": ("explore", "plan"),
    "debug": ("reproduce", "diagnose", "fix", "verify"),
    "multitask": ("decompose", "dispatch", "integrate"),
    "team": ("decompose", "dispatch", "integrate"),
    "cowork": ("work", "handoff"),
    "computer_use": ("observe", "interact", "verify"),
    "deep_research": ("collect", "compare", "synthesize"),
}


def _report(value: str, limit: int = 2000) -> str:
    text = value[:limit]
    for match in sorted(detect_pii(text), key=lambda item: item["start"], reverse=True):
        text = text[: match["start"]] + "[redacted]" + text[match["end"] :]
    return text[:limit]


class WorkModeService:
    def __init__(self, repos: RepoBundle) -> None:
        self.repos = repos
        self.events = RunEventRepo(repos.db)

    def _scope(self, owner: int, agent_id: str, thread_id: str) -> None:
        thread = self.repos.thread_repo.get(thread_id)
        if thread is None or thread.user_id != owner or thread.agent_id != agent_id:
            raise OctopError(ErrorCode.NOT_FOUND, "workflow thread unavailable")

    def begin(self, owner: int, agent_id: str, cfg: dict[str, Any]) -> dict[str, Any]:
        thread_id, run_id = str(cfg.get("thread_id") or ""), str(cfg.get("octop_task_run_id") or "")
        self._scope(owner, agent_id, thread_id)
        mode = cfg.get("work_mode") or "agentic"
        if mode not in STAGES or not run_id:
            raise OctopError(ErrorCode.FORBIDDEN, "invalid workflow mode or run")
        context = cfg.get("octop_execution_context") or {}
        event_id = f"workflow:{agent_id}:{thread_id}:{run_id}"
        self.events.save(
            event_id=event_id,
            owner=owner,
            agent_id=agent_id,
            thread_id=thread_id,
            run_id=run_id,
            context_id=context.get("context_id"),
            kind="workflow",
            status="in_progress",
            payload={
                "mode": mode,
                "version": 0,
                "stages": [{"name": name, "status": "pending"} for name in STAGES[mode]],
            },
            replace=False,
        )
        event = self.events.get(owner, event_id)
        if event is None or event["payload"]["mode"] != mode:
            raise OctopError(ErrorCode.FORBIDDEN, "workflow mode changed within a run")
        return event

    _EVIDENCE_KINDS = frozenset(
        {"tool", "device", "job", "plan", "dispatch", "interaction", "target"}
    )
    _FINAL_STATUSES = frozenset({"completed", "failed"})
    _TARGET_FINAL_STATUSES = frozenset({"completed", "failed", "bound"})

    def _lookup_evidence(
        self,
        owner: int,
        run_id: str,
        identity: str,
        *,
        agent_id: str | None = None,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a receipt id for this run.

        Models often paste the raw ``operation_id`` / tool UUID / ``call_*`` id
        instead of the RunEvent ``event_id`` (``operation:…`` / ``tool:…`` /
        ``context:…``). Try those prefixes, then ``payload.tool_call_id`` /
        ``payload.call_id``. ``work_step`` and ``kind=model`` are never evidence.
        """
        raw = str(identity or "").strip()
        if not raw:
            raise OctopError(ErrorCode.FORBIDDEN, "evidence id is empty")
        candidates = [raw]
        if ":" not in raw:
            candidates.extend(
                f"{prefix}:{raw}"
                for prefix in (
                    "operation",
                    "tool",
                    "dispatch",
                    "job",
                    "interaction",
                    "plan",
                    "context",
                )
            )

        wrong_run = False
        disallowed_kind: str | None = None
        work_step_named = False
        for candidate in candidates:
            item = self.events.get(owner, candidate)
            if item is None:
                continue
            if item["run_id"] != run_id:
                wrong_run = True
                continue
            if item["payload"].get("name") == "work_step":
                work_step_named = True
                continue
            kind = str(item["kind"])
            if kind == "model":
                disallowed_kind = "model"
                continue
            if kind not in self._EVIDENCE_KINDS:
                disallowed_kind = kind
                continue
            return item

        if agent_id and thread_id:
            for row in self.events.list(owner, agent_id, thread_id, run_id=run_id, limit=100):
                payload = row.get("payload") or {}
                if payload.get("tool_call_id") != raw and payload.get("call_id") != raw:
                    continue
                if payload.get("name") == "work_step":
                    raise OctopError(
                        ErrorCode.FORBIDDEN,
                        "work_step receipts are not evidence",
                        details={"evidence_id": raw},
                    )
                kind = str(row["kind"])
                if kind == "model":
                    raise OctopError(
                        ErrorCode.FORBIDDEN,
                        "model receipts are not workflow evidence",
                        details={"evidence_id": raw},
                    )
                if kind not in self._EVIDENCE_KINDS:
                    raise OctopError(
                        ErrorCode.FORBIDDEN,
                        f"evidence kind {kind} is not allowed",
                        details={"evidence_id": raw, "kind": kind},
                    )
                return row

        details = {"evidence_id": raw}
        if wrong_run:
            raise OctopError(
                ErrorCode.FORBIDDEN, "evidence must belong to this run", details=details
            )
        if work_step_named:
            raise OctopError(
                ErrorCode.FORBIDDEN, "work_step receipts are not evidence", details=details
            )
        if disallowed_kind == "model":
            raise OctopError(
                ErrorCode.FORBIDDEN,
                "model receipts are not workflow evidence",
                details=details,
            )
        if disallowed_kind is not None:
            raise OctopError(
                ErrorCode.FORBIDDEN,
                f"evidence kind {disallowed_kind} is not allowed",
                details={**details, "kind": disallowed_kind},
            )
        raise OctopError(ErrorCode.FORBIDDEN, "evidence not found in this run", details=details)

    def step(
        self,
        owner: int,
        agent_id: str,
        cfg: dict[str, Any],
        *,
        version: int,
        stage: str,
        status: str,
        report: str,
        evidence_ids: list[str],
        decision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = self.begin(owner, agent_id, cfg)
        previous = event["payload"]
        if previous["version"] != version:
            raise OctopError(
                ErrorCode.WORKFLOW_CONFLICT, "workflow changed; inspect its latest version"
            )
        if event["status"] == "completed":
            raise OctopError(ErrorCode.FORBIDDEN, "workflow already completed")
        if status not in {"in_progress", "completed", "blocked", "needs_input"}:
            raise OctopError(ErrorCode.FORBIDDEN, "invalid workflow status")
        index = next(
            (i for i, item in enumerate(previous["stages"]) if item["status"] != "completed"), None
        )
        if index is None or previous["stages"][index]["name"] != stage:
            raise OctopError(ErrorCode.FORBIDDEN, "complete the current workflow stage first")
        if not report.strip() or len(report) > 2000 or len(evidence_ids) > 16:
            raise OctopError(ErrorCode.FORBIDDEN, "provide a bounded workflow report and evidence")
        evidence = []
        for identity in dict.fromkeys(evidence_ids):
            item = self._lookup_evidence(
                owner,
                event["run_id"],
                identity,
                agent_id=agent_id,
                thread_id=str(cfg.get("thread_id") or ""),
            )
            finals = (
                self._TARGET_FINAL_STATUSES if item["kind"] == "target" else self._FINAL_STATUSES
            )
            if item["status"] not in finals:
                raise OctopError(
                    ErrorCode.FORBIDDEN,
                    "evidence has no final receipt",
                    details={
                        "evidence_id": identity,
                        "status": item["status"],
                        "kind": item["kind"],
                    },
                )
            evidence.append(item)
        payload = deepcopy(previous)
        entry = payload["stages"][index]
        if status == "completed":
            self._validate_completion(event, stage, evidence)
        if decision is not None:
            if payload["mode"] != "cowork" or stage != "handoff" or status != "needs_input":
                raise OctopError(ErrorCode.FORBIDDEN, "decisions are cowork handoff artifacts")
            options = decision.get("options")
            if (
                not isinstance(options, list)
                or not 2 <= len(options) <= 5
                or any(
                    not isinstance(item, str) or not item.strip() or len(item) > 200
                    for item in options
                )
                or len(set(options)) != len(options)
                or not isinstance(decision.get("question"), str)
                or not decision["question"].strip()
                or not isinstance(decision.get("recommendation"), int)
                or not 0 <= decision["recommendation"] < len(options)
            ):
                raise OctopError(ErrorCode.FORBIDDEN, "invalid cowork decision")
            entry["decision"] = {
                "question": _report(decision["question"], 1000),
                "options": [_report(item, 200) for item in options],
                "recommendation": decision["recommendation"],
            }
        elif payload["mode"] == "cowork" and stage == "handoff" and status == "needs_input":
            raise OctopError(ErrorCode.FORBIDDEN, "provide a question, options and recommendation")
        elif "decision" in entry:
            raise OctopError(ErrorCode.FORBIDDEN, "only the user can resolve this handoff")
        entry.update(
            status=status,
            report=_report(report),
            evidence_ids=[item["event_id"] for item in evidence],
            updated_at=time.time(),
        )
        payload["version"] += 1
        overall = (
            "completed"
            if all(item["status"] == "completed" for item in payload["stages"])
            else status
            if status != "completed"
            else "in_progress"
        )
        if not self.events.compare_payload(owner, event["event_id"], previous, payload, overall):
            raise OctopError(
                ErrorCode.WORKFLOW_CONFLICT, "workflow changed; inspect its latest version"
            )
        return self.events.get(owner, event["event_id"]) or {}

    def _validate_completion(
        self, event: dict[str, Any], stage: str, evidence: list[dict[str, Any]]
    ) -> None:
        payload = event["payload"]
        mode = payload["mode"]
        successful = [item for item in evidence if item["status"] == "completed"]
        if mode == "cowork" and stage == "handoff":
            raise OctopError(ErrorCode.FORBIDDEN, "only the user can resolve this handoff")
        if (
            mode == "plan"
            and stage == "plan"
            and not any(
                item["kind"] == "plan"
                and str(
                    item["payload"].get("file_path") or item["payload"].get("path") or ""
                ).startswith(("/.agent/plans/", "plans/"))
                for item in successful
            )
        ):
            raise OctopError(ErrorCode.FORBIDDEN, "reference a completed plan artifact")
        if mode == "debug":
            if stage in {"reproduce", "diagnose"} and not evidence:
                raise OctopError(
                    ErrorCode.FORBIDDEN,
                    "reference actual observations, including failed reproduction",
                )
            if stage == "verify":
                fix = payload["stages"][2]
                if not any(item["created_at"] >= fix["updated_at"] for item in successful):
                    raise OctopError(
                        ErrorCode.FORBIDDEN, "reference verification performed after the fix report"
                    )
        if mode in {"team", "multitask"} and stage == "dispatch":
            count = sum(item["kind"] == "dispatch" for item in successful)
            if count < (2 if mode == "multitask" else 1):
                raise OctopError(
                    ErrorCode.FORBIDDEN, "actual completed dispatch receipts are required"
                )
        if (
            mode == "computer_use"
            and stage == "interact"
            and not any(
                item["kind"] in {"device", "interaction"}
                and item["payload"].get("action") in {"desktop.input", "browser.action"}
                for item in successful
            )
        ):
            raise OctopError(ErrorCode.FORBIDDEN, "reference an actual device interaction session")
        if mode == "deep_research" and stage in {"collect", "compare"}:
            sources = {
                url
                for item in successful
                for url in item["payload"].get("source_urls", [])
                if isinstance(url, str)
            }
            if len(sources) < (2 if stage == "compare" else 1):
                raise OctopError(
                    ErrorCode.FORBIDDEN, "reference retrieved sources; comparison needs two URLs"
                )

    def decide(
        self, owner: int, agent_id: str, thread_id: str, event_id: str, *, version: int, choice: int
    ) -> dict[str, Any]:
        """Only the authenticated HTTP adapter calls this; no model tool exposes it."""
        self._scope(owner, agent_id, thread_id)
        event = self.events.get(owner, event_id)
        if event is None or (event["agent_id"], event["thread_id"], event["kind"]) != (
            agent_id,
            thread_id,
            "workflow",
        ):
            raise OctopError(ErrorCode.NOT_FOUND, "workflow unavailable")
        previous = event["payload"]
        if previous["version"] != version or event["status"] != "needs_input":
            raise OctopError(ErrorCode.WORKFLOW_CONFLICT, "handoff changed")
        payload = deepcopy(previous)
        stage = payload["stages"][-1]
        decision = stage.get("decision")
        if not decision or type(choice) is not int or not 0 <= choice < len(decision["options"]):
            raise OctopError(ErrorCode.FORBIDDEN, "invalid handoff choice")
        decision.update(choice=choice, decided_by=owner, decided_at=time.time())
        stage["status"] = "completed"
        payload["version"] += 1
        if not self.events.compare_payload(owner, event_id, previous, payload, "completed"):
            raise OctopError(ErrorCode.WORKFLOW_CONFLICT, "handoff changed")
        return self.events.get(owner, event_id) or {}


def build_work_mode_tools(service: WorkModeService, agent_id: str) -> list[Any]:
    @tool
    def work_step(
        stage: str = "",
        version: int = 0,
        status: str = "in_progress",
        report: str = "",
        evidence_ids: list[str] | None = None,
        decision: dict[str, Any] | None = None,
    ) -> str:
        """Inspect or advance this run's persistent work-mode stages.

        Empty stage inspects the latest workflow and receipt IDs. To advance,
        use its exact version/current stage, report findings and reference final
        RunEvent event_ids. Never invent evidence or mark accepted jobs done.
        blocked records a capability/problem; cowork handoff uses needs_input
        and decision={question,options:[...],recommendation:0}. Only the user can
        answer a decision. Stage completion is distinct from free-form chat.
        """
        cfg = get_config().get("configurable") or {}
        owner = int(cfg.get("user") or 0)
        ids = evidence_ids or []
        try:
            event = (
                service.step(
                    owner,
                    agent_id,
                    cfg,
                    stage=stage,
                    version=version,
                    status=status,
                    report=report,
                    evidence_ids=ids,
                    decision=decision,
                )
                if stage
                else service.begin(owner, agent_id, cfg)
            )
        except OctopError as exc:
            return json.dumps(
                {
                    "ok": False,
                    "error": exc.message,
                    "code": exc.code.value,
                    "bad_evidence_id": (exc.details or {}).get("evidence_id"),
                    "bad_evidence_ids": list(dict.fromkeys(ids)),
                    "details": exc.details,
                },
                ensure_ascii=False,
            )
        receipts = service.events.list(
            owner, agent_id, str(cfg["thread_id"]), run_id=str(cfg["octop_task_run_id"]), limit=100
        )
        usable = [
            item
            for item in receipts
            if item["kind"] != "workflow" and item["payload"].get("name") != "work_step"
        ]
        return json.dumps(
            {
                "workflow": event,
                "receipts": usable,
            },
            ensure_ascii=False,
        )

    return [work_step]
