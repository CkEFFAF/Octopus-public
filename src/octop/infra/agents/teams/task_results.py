"""Invocation-bound expert reports, finalized only by trusted host history evidence."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from octop.i18n import tr
from octop.infra.agents.teams.collaboration import runtime_config
from octop.infra.documents.resources import ResourceService, denied
from octop.infra.errors import OctopError
from octop.infra.utils.llm_text import strip_thinking


class TaskResultInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["succeeded", "blocked", "failed", "needs_input"]
    summary: str = Field(min_length=1, max_length=2000)
    resource_ids: list[str] = Field(default_factory=list, max_length=20)


def final_reply(
    manager: Any, owner: int, invocation: dict[str, Any], end: int, *, start: int | None = None
) -> dict[str, Any] | None:
    child = invocation.get("child_thread_id")
    if not child:
        return None
    try:
        ResourceService(manager).scope(owner, invocation["callee_agent_id"], child)
    except OctopError:
        return None
    rows = manager._repos.thread_message_repo.range_page(
        child, max(invocation.get("history_start", 0), start or 0), end, 100
    )
    for row in rows:
        if row.role not in {"ai", "assistant"}:
            # Only the host's mechanically appended assignment may trail a
            # pre-persisted answer. Other user/tool messages do not prove finality.
            if (
                row.role in {"human", "user"}
                and row.message_id
                and row.message_id.startswith(f"team-peer:{child}:")
                and row.message_id.endswith(":human")
            ):
                continue
            return None
        try:
            wire = json.loads(row.message_json)
        except (TypeError, ValueError):
            return None
        if not isinstance(wire, dict):
            return None
        data = wire.get("data", wire)
        if not isinstance(data, dict):
            return None
        if data.get("tool_calls") or (data.get("additional_kwargs") or {}).get("tool_calls"):
            return None
        content = data.get("content", "")
        if isinstance(content, list):
            content = "\n".join(
                block["text"]
                for block in content
                if isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            )
        if isinstance(content, str) and strip_thinking(content).strip():
            return {"thread_id": child, "seq": row.seq, "message_id": row.message_id}
        return None
    return None


class TaskResultService:
    def __init__(self, manager: Any) -> None:
        self.manager = manager
        self.repo = manager._repos.collaboration_repo
        self.resources = ResourceService(manager)

    def _resources(
        self, owner: int, invocation: dict[str, Any], ids: list[str]
    ) -> list[dict[str, str]]:
        evidence = []
        for identity in ids:
            resource = self.repo.get("collaboration_resources", owner, identity)
            if not resource or (
                resource.get("producer_invocation_id") != invocation["invocation_id"]
                or resource.get("source_agent_id") != invocation["callee_agent_id"]
                or resource.get("source_thread_id") != invocation["child_thread_id"]
                or resource.get("scope_thread_id") != invocation["scope_thread_id"]
                or resource.get("publication_state") != "published"
            ):
                raise denied()
            evidence.append({"resource_id": identity, "version": resource["version"]})
        return evidence

    def report(self, agent: str, cfg: dict[str, Any], request: TaskResultInput) -> dict[str, Any]:
        owner = int(cfg.get("user") or 0)
        identity = str(cfg.get("octop_invocation_id") or "")
        item = self.repo.get("collaboration_invocations", owner, identity)
        if (
            not item
            or (item["callee_agent_id"], item.get("child_thread_id"))
            != (agent, cfg.get("thread_id"))
            or not cfg.get("octop_child_bound")
        ):
            raise denied()
        self.resources.scope(owner, agent, item["child_thread_id"])
        if item["transport_status"] != "running":
            raise ValueError("TASK_RESULT_NOT_RUNNING")
        summary = strip_thinking(request.summary).strip()
        if not summary or len(request.resource_ids) != len(set(request.resource_ids)):
            raise ValueError("TASK_RESULT_INVALID")
        evidence = self._resources(owner, item, request.resource_ids)
        candidate = {"outcome": request.outcome, "summary": summary, "resources": evidence}
        fingerprint = hashlib.sha256(json.dumps(candidate, sort_keys=True).encode()).hexdigest()
        candidate["fingerprint"] = fingerprint
        previous = item.get("pending_task_result")
        if previous:
            if previous == candidate:
                return {"status": "pending", "outcome": request.outcome}
            raise ValueError("TASK_RESULT_CONFLICT")
        saved = self.repo.save(
            "collaboration_invocations",
            owner,
            identity,
            item["scope_thread_id"],
            {**item, "pending_task_result": candidate},
            "delegation.result_reported",
            event_id=f"{identity}:result_reported",
            invocation_id=identity,
            previous=item,
        )
        if not saved:
            current = self.repo.get("collaboration_invocations", owner, identity)
            if (
                not current
                or current.get("pending_task_result") != candidate
                or current["transport_status"] != "running"
            ):
                raise ValueError("TASK_RESULT_CONFLICT")
        return {"status": "pending", "outcome": request.outcome}

    def prepare_result(self, call: Any, thread: str, result: dict[str, Any]) -> None:
        # Arbitrary returned metadata is never an authority for business outcomes.
        result.pop("dispatch_receipt", None)
        owner = int(call.user_id)
        item = self.repo.get("collaboration_invocations", owner, call.invocation_id)
        if not item or item["transport_status"] != "running":
            return
        if (
            item["source_agent_id"],
            item["callee_agent_id"],
            item["source_thread_id"],
            item.get("child_thread_id"),
        ) != (call.from_agent_id, call.to_agent_id, call.source_thread_id, thread):
            raise denied()
        candidate = item.get("pending_task_result")
        if not candidate:
            return
        if item.get("cancel_requested"):
            self._provisional_reason(owner, item, "TASK_RESULT_UNCONFIRMED")
            return
        end = self.manager._repos.thread_message_repo.head(item["child_thread_id"])
        reply = final_reply(self.manager, owner, item, end)
        from octop.infra.agents.teams.team_manager import (
            _history_projection_messages,
            _peer_turn_messages,
        )
        from octop.infra.history.projection import message_inputs

        messages = result.get("messages")
        visible = _peer_turn_messages(messages if isinstance(messages, list) else [])
        projected = message_inputs(_history_projection_messages(visible), dedupe_missing_ids=True)
        expected = projected[-1] if projected else None
        if (
            not reply
            or not expected
            or expected.role not in {"ai", "assistant"}
            or reply["message_id"] != expected.message_id
        ):
            self._provisional_reason(owner, item, "TASK_RESULT_EVIDENCE_MISSING")
            return
        rows = self.manager._repos.thread_message_repo.range_page(
            thread, reply["seq"] - 1, reply["seq"], 1
        )
        stored = json.loads(rows[0].message_json)
        expected_wire = json.loads(expected.message_json)
        if stored.get("data", stored).get("content") != expected_wire.get(
            "data", expected_wire
        ).get("content"):
            self._provisional_reason(owner, item, "TASK_RESULT_EVIDENCE_MISSING")
            return
        evidence = self._resources(owner, item, [r["resource_id"] for r in candidate["resources"]])
        if evidence != candidate["resources"]:
            raise ValueError("TASK_RESULT_EVIDENCE_MISSING")
        ready = {**candidate, "reply": reply, "history_end": end, "provenance": "expert_reported"}
        if not self.repo.save(
            "collaboration_invocations",
            owner,
            item["invocation_id"],
            item["scope_thread_id"],
            {**item, "ready_task_result": ready},
            "delegation.result_ready",
            event_id=f"{item['invocation_id']}:result_ready",
            invocation_id=item["invocation_id"],
            previous=item,
        ):
            result["dispatch_receipt"] = {
                "task_outcome": "unknown",
                "error_code": "TASK_RESULT_CONFLICT",
            }
            return
        result["dispatch_receipt"] = {"task_outcome": candidate["outcome"]}

    def _provisional_reason(self, owner: int, item: dict[str, Any], reason: str) -> None:
        self.repo.save(
            "collaboration_invocations",
            owner,
            item["invocation_id"],
            item["scope_thread_id"],
            {**item, "task_result_reason": reason},
            "delegation.result_unconfirmed",
            event_id=f"{item['invocation_id']}:result_unconfirmed",
            invocation_id=item["invocation_id"],
            previous=item,
        )


def build_task_result_tools(manager: Any, agent_id: str) -> list[StructuredTool]:
    service = TaskResultService(manager)

    async def report_task_result(
        outcome: Literal["succeeded", "blocked", "failed", "needs_input"],
        summary: str,
        resource_ids: list[str] | None = None,
    ) -> str:
        """Report your task's business outcome before your final public answer.

        This records an expert claim, independently of call completion. Use only
        resources you published in this invocation; text answers need no files.
        The report stays pending until the host persists your final answer.
        """
        cfg = runtime_config()
        try:
            request = TaskResultInput(
                outcome=outcome, summary=summary, resource_ids=resource_ids or []
            )
            return json.dumps(service.report(agent_id, cfg, request), ensure_ascii=False)
        except Exception as exc:
            code = (
                str(exc)
                if isinstance(exc, ValueError) and str(exc).startswith("TASK_RESULT_")
                else "TASK_RESULT_DENIED"
            )
            return json.dumps(
                {
                    "status": "error",
                    "code": code,
                    "retryable": False,
                    "error": tr("taskResults.unavailable", str(cfg.get("language") or "en")),
                },
                ensure_ascii=False,
            )

    return [StructuredTool.from_function(coroutine=report_task_result, args_schema=TaskResultInput)]
