"""Application-owned invocation persistence around Harness peer lifecycle."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import asdict, is_dataclass
from typing import Any

from langgraph.config import get_config

from octop.infra.db.services import RepoBundle
from octop.infra.documents.resources import ResourceService, denied


def runtime_config() -> dict[str, Any]:
    try:
        return dict(get_config().get("configurable") or {})
    except RuntimeError:
        return {}


def options(call: Any) -> dict[str, Any]:
    value = getattr(call, "dispatch_options", None)
    return asdict(value) if is_dataclass(value) and not isinstance(value, type) else {}


class CollaborationService:
    def __init__(self, manager: Any) -> None:
        self.manager = manager
        self.repos: RepoBundle = manager._repos
        self.repo = self.repos.collaboration_repo
        self.resources = ResourceService(manager)

    def public(self, invocation: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in invocation.items()
            if key
            not in {
                "scope_thread_id",
                "bound_configurable",
                "parent_configurable",
                "job_id",
                "history_start",
                "history_end",
                "request_fingerprint",
                "_newly_claimed",
                "assignment",
                "source_session_key",
            }
        }

    def accept(self, call: Any) -> dict[str, Any]:
        owner = int(call.user_id)
        identity = str(getattr(call, "invocation_id", "") or "")
        if not identity or not call.source_thread_id:
            raise denied()
        self.resources.scope(owner, call.from_agent_id, call.source_thread_id)
        dispatch = options(call)
        if len(str(call.message)) > 32000:
            raise ValueError("COLLABORATION_ASSIGNMENT_TOO_LARGE")
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "source": call.from_agent_id,
                    "callee": call.to_agent_id,
                    "thread": call.source_thread_id,
                    "message": call.message,
                    "options": dispatch,
                    "retry_of": getattr(call, "retry_of", None),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        existing = self.repo.get("collaboration_invocations", owner, identity)
        if existing:
            if existing.get("request_fingerprint") != fingerprint:
                raise ValueError("INVOCATION_CONFLICT")
            if (
                existing["source_agent_id"],
                existing["callee_agent_id"],
                existing["source_thread_id"],
            ) != (call.from_agent_id, call.to_agent_id, call.source_thread_id):
                raise denied()
            return dict(existing)
        cfg = runtime_config()
        parent_id = cfg.get("octop_invocation_id")
        parent = self.repo.get("collaboration_invocations", owner, parent_id or "")
        if parent_id and (
            not parent
            or (parent["callee_agent_id"], parent["child_thread_id"])
            != (call.from_agent_id, call.source_thread_id)
        ):
            raise denied()
        scope = parent["scope_thread_id"] if parent else call.source_thread_id
        resource_ids = list(dispatch.get("resource_ids") or [])
        callee = self.repos.agent_repo.get(call.to_agent_id)
        if callee is None or (resource_ids and callee.user_id != owner):
            raise denied()
        # Authorize all requested versions before accepting any execution.
        resources = [
            self.resources.authorize(
                owner, item, call.from_agent_id, call.source_thread_id, parent_id
            )
            for item in resource_ids
        ]
        now = time.time()
        retry_of = getattr(call, "retry_of", None)
        if retry_of:
            prior = self.repo.get("collaboration_invocations", owner, retry_of)
            if (
                not prior
                or prior["scope_thread_id"] != scope
                or prior["callee_agent_id"] != call.to_agent_id
                or prior["transport_status"] not in {"failed", "cancelled", "unknown"}
            ):
                raise denied()
        invocation = {
            "invocation_id": identity,
            "source_agent_id": call.from_agent_id,
            "callee_agent_id": call.to_agent_id,
            "source_thread_id": call.source_thread_id,
            "child_thread_id": None,
            "scope_thread_id": scope,
            "root_run_id": parent["root_run_id"]
            if parent
            else str(cfg.get("octop_task_run_id") or identity),
            "parent_invocation_id": parent_id,
            "retry_of": retry_of,
            "transport_status": "accepted",
            "task_outcome": "unknown",
            "target_policy": dispatch.get("target_policy", "member_default"),
            "requested_target": {
                key: dispatch.get(key)
                for key in ("device_id", "target_kind", "working_dir")
                if dispatch.get(key) is not None
            },
            "resolved_target": None,
            "error_code": None,
            "retryable": False,
            "prompt": str(call.message)[:8000],
            "assignment": str(call.message),
            "source_session_key": call.source_session_key,
            "resource_ids": resource_ids,
            "created_at": now,
            "updated_at": now,
            "parent_configurable": {
                key: cfg[key]
                for key in (
                    "octop_execution_context",
                    "octop_device_target",
                    "conversation_mode",
                    "work_mode",
                    "skills",
                    "mcp_servers",
                    "octop_task_run_id",
                )
                if key in cfg
            },
            "job_id": getattr(call, "job_id", None),
            "request_fingerprint": fingerprint,
        }
        claimed = self.repo.save(
            "collaboration_invocations",
            owner,
            identity,
            scope,
            invocation,
            "delegation.accepted",
            event_id=f"{identity}:accepted",
            invocation_id=identity,
            grants=resources,
        )
        saved = self.repo.get("collaboration_invocations", owner, identity) or invocation
        if saved["request_fingerprint"] != fingerprint:
            raise ValueError("INVOCATION_CONFLICT")
        return {**saved, "_newly_claimed": claimed}

    def prepare(self, call: Any, thread: str, extra: dict[str, Any]) -> dict[str, Any]:
        from octop.infra.agents.teams.target_visibility import apply_target_policy

        invocation = self.accept(call)
        if invocation.get("bound_configurable") is not None:
            return dict(invocation["bound_configurable"])
        owner = int(call.user_id)
        dispatch = options(call)
        cfg = dict(invocation["parent_configurable"])
        callee = self.repos.agent_repo.get(call.to_agent_id)
        if callee is None:
            raise denied()
        if callee.user_id != owner:
            if dispatch.get("resource_ids") or dispatch.get("target_policy") == "explicit":
                raise denied()
            cfg = {"conversation_mode": "ask", "work_mode": "ask", "skills": [], "mcp_servers": []}
        else:
            snapshot = apply_target_policy(
                {"configurable": cfg},
                policy=dispatch.get("target_policy"),
                explicit=dispatch,
                devices=self.manager._device_service,
                owner=owner,
            )
            cfg = snapshot["configurable"]
            request = self.manager._prepare_stream_request(
                call.to_agent_id,
                {
                    "agent_id": call.to_agent_id,
                    "user": owner,
                    "thread_id": thread,
                    "conversation_mode": cfg.get("conversation_mode")
                    if cfg.get("conversation_mode") in {"ask", "plan"}
                    else None,
                    "configurable": {**cfg, "octop_task_run_id": invocation["root_run_id"]},
                },
            )
            cfg = request["configurable"]
        return self.bind(call, thread, {**cfg, **extra, "octop_child_bound": True})

    async def lifecycle(self, call: Any, receipt: Any) -> Any:
        invocation = self.accept(call)
        claimed = invocation.pop("_newly_claimed", False)
        status = receipt.transport_status
        if receipt.error_code == "PEER_CANCEL_REQUESTED":
            self.request_cancel(int(call.user_id), invocation["invocation_id"])
            invocation = (
                self.repo.get(
                    "collaboration_invocations", int(call.user_id), invocation["invocation_id"]
                )
                or invocation
            )
        if status == "accepted":
            if claimed:
                return None
            from octop_harness.teams.util import DispatchReceipt

            return DispatchReceipt(
                **{
                    key: invocation[key]
                    for key in (
                        "invocation_id",
                        "transport_status",
                        "task_outcome",
                        "target_policy",
                        "requested_target",
                        "resolved_target",
                        "error_code",
                        "retryable",
                        "source_thread_id",
                        "child_thread_id",
                        "root_run_id",
                    )
                }
            )
        if invocation["transport_status"] in {"completed", "failed", "cancelled"}:
            return
        if invocation["transport_status"] == status:
            return
        allowed = {
            "accepted": {"running", "failed", "cancelled", "unknown"},
            "running": {"completed", "failed", "cancelled", "unknown"},
            "unknown": {"completed", "failed", "cancelled"},
        }
        if status not in allowed.get(invocation["transport_status"], set()):
            raise ValueError("INVOCATION_TRANSITION_INVALID")
        payload = {
            key: value
            for key, value in asdict(receipt).items()
            if key
            in {
                "transport_status",
                "task_outcome",
                "error_code",
                "retryable",
                "resolved_target",
            }
        }
        # Missing target metadata from a later receipt cannot erase resolved identity.
        if payload.get("resolved_target") is None:
            payload.pop("resolved_target", None)
        updated = {**invocation, **payload, "updated_at": time.time()}
        if status == "completed" and invocation.get("cancel_requested"):
            updated["cancel_too_late"] = True
        if status in {"completed", "failed", "cancelled", "unknown"} and invocation.get(
            "child_thread_id"
        ):
            updated["history_end"] = self._last_seq(invocation["child_thread_id"])
        changed = self.repo.save(
            "collaboration_invocations",
            int(call.user_id),
            invocation["invocation_id"],
            invocation["scope_thread_id"],
            updated,
            "delegation.result_unknown"
            if status == "unknown"
            else f"delegation.{status if status != 'running' else 'started'}",
            event_id=f"{invocation['invocation_id']}:{status}",
            invocation_id=invocation["invocation_id"],
            previous=invocation,
        )
        if not changed:
            current = self.repo.get(
                "collaboration_invocations", int(call.user_id), invocation["invocation_id"]
            )
            if current is not None and current["transport_status"] in {
                "completed",
                "failed",
                "cancelled",
            }:
                return None
            if (
                current is not None
                and current.get("cancel_requested")
                and not invocation.get("cancel_requested")
            ):
                return await self.lifecycle(call, receipt)
            if current is None or current["transport_status"] != status:
                raise ValueError("INVOCATION_TRANSITION_CONFLICT")

    def active(self, owner: int, run: str) -> list[dict[str, Any]]:
        with self.repos.db.connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM collaboration_invocations WHERE owner_user_id=? AND root_run_id=?",
                (owner, run),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    async def wait_for_run(self, owner: int, run: str) -> None:
        while True:
            items = self.active(owner, run)
            if any(
                item["transport_status"] in {"failed", "cancelled", "unknown"} for item in items
            ):
                raise RuntimeError("COLLABORATION_RESULT_UNCONFIRMED")
            if all(item["transport_status"] == "completed" for item in items):
                return
            await asyncio.sleep(0.1)

    async def cancel_run(self, owner: int, run: str) -> None:
        team = self.manager._harness_manager.team
        for item in self.active(owner, run):
            if item["transport_status"] not in {"accepted", "running"}:
                continue
            self.request_cancel(owner, item["invocation_id"])
            await team.acancel_peer(item["invocation_id"])

    def request_cancel(self, owner: int, identity: str) -> None:
        for _ in range(3):
            item = self.repo.get("collaboration_invocations", owner, identity)
            if item is None or item.get("cancel_requested") or item.get("cancel_too_late"):
                return
            terminal = item["transport_status"] in {"completed", "failed", "cancelled"}
            updated = {
                **item,
                "cancel_too_late" if terminal else "cancel_requested": True,
                "cancel_requested_at": time.time(),
                "updated_at": time.time(),
            }
            if self.repo.save(
                "collaboration_invocations",
                owner,
                identity,
                item["scope_thread_id"],
                updated,
                "delegation.cancel_too_late" if terminal else "delegation.cancel_requested",
                event_id=f"{identity}:cancel_too_late"
                if terminal
                else f"{identity}:cancel_requested",
                invocation_id=identity,
                previous=item,
            ):
                return
        raise ValueError("INVOCATION_TRANSITION_CONFLICT")

    def reconcile_startup(self) -> None:
        with self.repos.db.connect() as conn:
            rows = conn.execute(
                "SELECT owner_user_id,payload_json FROM collaboration_invocations WHERE transport_status IN ('accepted','running')"
            ).fetchall()
        for row in rows:
            item = json.loads(row["payload_json"])
            if item["transport_status"] not in {"accepted", "running"}:
                continue
            updated = {
                **item,
                "transport_status": "unknown",
                "error_code": "COLLABORATION_RESTART_UNCONFIRMED",
                "retryable": False,
                "updated_at": time.time(),
            }
            self.repo.save(
                "collaboration_invocations",
                row["owner_user_id"],
                item["invocation_id"],
                item["scope_thread_id"],
                updated,
                "delegation.result_unknown",
                event_id=f"{item['invocation_id']}:restart",
                invocation_id=item["invocation_id"],
                previous=item,
            )

    def _last_seq(self, thread: str) -> int:
        with self.repos.db.connect() as conn:
            row = conn.execute(
                "SELECT MAX(seq) AS n FROM thread_messages WHERE thread_id=?", (thread,)
            ).fetchone()
        return int(row["n"] or 0) if row else 0

    def bind(self, call: Any, thread: str, configurable: dict[str, Any]) -> dict[str, Any]:
        invocation = self.accept(call)
        if invocation.get("bound_configurable") is not None:
            return dict(invocation["bound_configurable"])
        owner = int(call.user_id)
        cfg = {
            **configurable,
            "octop_invocation_id": invocation["invocation_id"],
            "octop_root_thread_id": invocation["scope_thread_id"],
            "octop_task_run_id": invocation["root_run_id"],
            "octop_resource_ids": invocation["resource_ids"],
        }
        supplied = cfg.get("octop_execution_context")
        resolved = None
        if isinstance(supplied, dict):
            resolved = {
                key: supplied.get(key)
                for key in ("context_id", "device_id", "target_kind", "working_dir", "work_mode")
            }
            device_id = supplied.get("device_id")
            if device_id and self.manager._device_service is not None:
                device = self.manager._device_service.owned(owner, device_id)
                resolved["device_name"] = getattr(device, "name", None)
        updated = {
            **invocation,
            "child_thread_id": thread,
            "bound_configurable": cfg,
            "resolved_target": resolved,
            "history_start": self._last_seq(thread),
            "updated_at": time.time(),
        }
        self.repo.save(
            "collaboration_invocations",
            owner,
            invocation["invocation_id"],
            invocation["scope_thread_id"],
            updated,
            "delegation.target_resolved",
            event_id=f"{invocation['invocation_id']}:target",
            invocation_id=invocation["invocation_id"],
            previous=invocation,
        )
        saved = self.repo.get("collaboration_invocations", owner, invocation["invocation_id"])
        return dict((saved or updated)["bound_configurable"])

    def listing(
        self, owner: int, agent: str, thread: str, after: int, limit: int
    ) -> dict[str, Any]:
        self.resources.scope(owner, agent, thread)
        events = self.repo.events(owner, thread, after, limit + 1)
        page = events[:limit]
        artifacts = self.repo.list("collaboration_resources", owner, thread)
        invocations = self.repo.list("collaboration_invocations", owner, thread)
        artifact_refs = list({event["resource_id"] for event in page if event.get("resource_id")})
        invocation_refs = list(
            {event["invocation_id"] for event in page if event.get("invocation_id")}
        )
        artifacts = list(
            {
                item["resource_id"]: item
                for item in [
                    *artifacts,
                    *self.repo.references("collaboration_resources", owner, thread, artifact_refs),
                ]
            }.values()
        )
        invocations = list(
            {
                item["invocation_id"]: item
                for item in [
                    *invocations,
                    *self.repo.references(
                        "collaboration_invocations", owner, thread, invocation_refs
                    ),
                ]
            }.values()
        )
        # Child-published versions keep their source identity but share the root scope.
        return {
            "invocations": [self.public(item) for item in invocations],
            "events": page,
            "artifacts": [self.resources.public(item, agent, thread) for item in artifacts],
            "next_cursor": page[-1]["seq"] if page else after,
            "has_more": len(events) > limit,
        }

    def detail(
        self, owner: int, agent: str, thread: str, identity: str, before_seq: int | None, limit: int
    ) -> dict[str, Any]:
        self.resources.scope(owner, agent, thread)
        item = self.repo.get("collaboration_invocations", owner, identity)
        if item is None or item["scope_thread_id"] != thread:
            raise denied()
        child = item.get("child_thread_id")
        messages = []
        if child:
            self.resources.scope(owner, item["callee_agent_id"], child)
            end = min(
                before_seq - 1 if before_seq is not None else 2**63 - 1,
                item.get("history_end", 2**63 - 1),
            )
            rows = self.repos.thread_message_repo.range_page(
                child, item.get("history_start", 0), end, limit + 1
            )
            for row in rows[:limit]:
                if row.role not in {"human", "user", "ai", "assistant"}:
                    continue
                wire = json.loads(row.message_json)
                data = wire.get("data", wire)
                content = data.get("content", "")
                # Deliberately expose public text only; never additional_kwargs/reasoning.
                if isinstance(content, list):
                    content = "\n".join(
                        str(block.get("text", ""))
                        for block in content
                        if isinstance(block, dict) and block.get("type") == "text"
                    )
                messages.append(
                    {
                        "seq": row.seq,
                        "role": {"human": "user", "ai": "assistant"}.get(row.role, row.role),
                        "content": str(content)[:4000],
                        "created_at": row.created_at,
                    }
                )
            more = len(rows) > limit
        else:
            more = False
        return {
            "invocation": self.public(item),
            "messages": list(reversed(messages)),
            "has_more": more,
            "next_before": rows[limit - 1].seq if child and more else None,
        }
