"""Persisted plan declarations and factual activity snapshots, without scheduling."""

from __future__ import annotations

import hashlib
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from octop.infra.agents.teams.collaboration import CollaborationService
from octop.infra.documents.resources import ResourceService
from octop.infra.execution.events import RunInspectionService


class PlanTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(min_length=1, max_length=100, pattern="^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=500)
    depends_on: list[str] = Field(default_factory=list, max_length=64)
    status: Literal["pending", "running", "completed", "failed", "blocked"] = "pending"
    reason: str = Field(default="", max_length=1000)


class WorkPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str = Field(min_length=1, max_length=100, pattern="^[A-Za-z0-9_-]+$")
    revision: int = Field(ge=0)
    tasks: list[PlanTask] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def acyclic(self) -> WorkPlan:
        tasks = {task.task_id: task for task in self.tasks}
        if len(tasks) != len(self.tasks):
            raise ValueError("PLAN_DUPLICATE_TASK")
        visited: set[str] = set()
        stack: set[str] = set()

        def visit(identity: str) -> None:
            if identity in stack:
                raise ValueError("PLAN_DEPENDENCY_CYCLE")
            if identity in visited:
                return
            if identity not in tasks:
                raise ValueError("PLAN_DEPENDENCY_MISSING")
            stack.add(identity)
            for dependency in tasks[identity].depends_on:
                visit(dependency)
            stack.remove(identity)
            visited.add(identity)

        for identity in tasks:
            visit(identity)
        return self


class ActivityService:
    def __init__(self, manager: Any) -> None:
        self.manager = manager
        self.resources = ResourceService(manager)
        self.repos = self.resources.repos

    def plan(self, owner: int, agent: str, thread: str, run: str, body: WorkPlan) -> dict[str, Any]:
        self.resources.scope(owner, agent, thread)
        if not run:
            raise ValueError("PLAN_RUN_REQUIRED")
        identity = (
            "plan_"
            + hashlib.sha256(f"{owner}:{agent}:{thread}:{run}:{body.plan_id}".encode()).hexdigest()[
                :32
            ]
        )
        other_plans = self.repos.workbench_repo.list(owner, agent, thread, "plan")
        declared_ids = {
            task["task_id"]
            for plan in other_plans
            if plan["run_id"] == run and plan["record_id"] != identity
            for task in plan["tasks"]
        }
        if any(task.task_id in declared_ids for task in body.tasks):
            raise ValueError("PLAN_TASK_ID_ALREADY_DECLARED")
        value = {
            **body.model_dump(),
            "record_id": identity,
            "run_id": run,
            "revision": body.revision + 1,
            "updated_at": time.time(),
        }
        if not self.repos.workbench_repo.save(
            owner, agent, thread, "plan", identity, value, expected=body.revision
        ):
            raise ValueError("PLAN_REVISION_CONFLICT")
        return value

    def snapshot(
        self, owner: int, agent: str, thread: str, before: int | None = None
    ) -> dict[str, Any]:
        self.resources.scope(owner, agent, thread)
        inspection = RunInspectionService(self.repos)
        # A bounded current window; older immutable identities remain explicitly pageable.
        page = inspection.list(owner, agent, thread, before=before, limit=200)
        events = page["events"]
        active = inspection.events.active(owner, agent, thread, limit=201) if before is None else []
        events = list({event["event_id"]: event for event in [*active[:200], *events]}.values())
        plans = self.repos.workbench_repo.list(owner, agent, thread, "plan")
        invocations = CollaborationService(self.manager).listing(owner, agent, thread, 0, 1)[
            "invocations"
        ]
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, str]] = []
        tasks: dict[tuple[str, str], str] = {}
        for plan in plans:
            for task in plan["tasks"]:
                identity = f"{plan['record_id']}:{task['task_id']}"
                tasks[(plan["run_id"], task["task_id"])] = identity
                nodes.append(
                    {
                        "id": identity,
                        "type": "plan",
                        "name": task["title"],
                        "task_id": task["task_id"],
                        "run_id": plan["run_id"],
                        "status": "waiting" if task["depends_on"] else "pending",
                        "declared_status": task["status"],
                        "reason": task["reason"],
                        "depends_on": task["depends_on"],
                        "updated_at": plan["updated_at"],
                        "dependencies_known": True,
                    }
                )
                edges.extend(
                    {
                        "from": f"{plan['record_id']}:{dependency}",
                        "to": identity,
                        "kind": "depends_on",
                    }
                    for dependency in task["depends_on"]
                )
        ids = {event["event_id"] for event in events}
        now = time.time()
        live = self.manager.steering_status(agent, thread)
        live_run = live.get("run_id") if live else None
        for event in events:
            payload = event["payload"]
            if event["kind"] not in {"dispatch", "job", "tool", "device"}:
                continue
            task = tasks.get((event["run_id"], str(payload.get("task_id") or "")))
            status = {"started": "running", "accepted": "waiting"}.get(
                event["status"], event["status"]
            )
            observation = (
                "stale"
                if status in {"running", "waiting"}
                and (
                    payload.get("observation", {}).get("status") == "unavailable"
                    or (
                        now - event["updated_at"] > 45
                        and (event["kind"] == "job" or event["run_id"] != live_run)
                    )
                )
                else "current"
            )
            node = {
                "id": event["event_id"],
                "type": "subagent" if event["kind"] == "dispatch" else event["kind"],
                "name": payload.get("subagent_type")
                or payload.get("name")
                or payload.get("action")
                or payload.get("job_id")
                or event["kind"],
                "status": status,
                "observed_status": observation,
                "outcome": payload.get("task_outcome", "unknown"),
                "run_id": event["run_id"],
                "context_id": event["context_id"],
                "task_id": payload.get("task_id") if task else None,
                "attempt_id": payload.get("attempt_id") or event["event_id"],
                "updated_at": event["updated_at"],
                "created_at": event["created_at"],
                "details": payload,
                "dependencies_known": bool(task),
            }
            nodes.append(node)
            if task:
                edges.append({"from": task, "to": node["id"], "kind": "contains"})
            parent = "tool:" + str(payload.get("parent_run_id") or "")
            if parent in ids:
                edges.append({"from": parent, "to": node["id"], "kind": "contains"})
        for invocation in invocations:
            nodes.append(
                {
                    "id": invocation["invocation_id"],
                    "type": "delegation",
                    "name": invocation["callee_agent_id"],
                    "status": invocation["transport_status"],
                    "outcome": invocation["task_outcome"],
                    "run_id": invocation["root_run_id"],
                    "updated_at": invocation["updated_at"],
                    "created_at": invocation["created_at"],
                    "details": invocation,
                    "dependencies_known": False,
                    "observed_status": "current"
                    if now - invocation["updated_at"] <= 45
                    or invocation["transport_status"] not in {"running", "accepted"}
                    else "stale",
                }
            )
        # A public ask_agent dispatch and its durable collaboration invocation
        # are two observations of one execution, only with exact source scope.
        canonical = {node["id"]: node for node in nodes if node["type"] == "delegation"}
        remap: dict[str, str] = {}
        for node in nodes:
            payload = node.get("details") or {}
            invocation_id = payload.get("invocation_id")
            target = canonical.get(str(invocation_id))
            invocation = (
                self.repos.collaboration_repo.get(
                    "collaboration_invocations", owner, str(invocation_id)
                )
                if target
                else None
            ) or {}
            if (
                node["type"] != "subagent"
                or payload.get("name") != "ask_agent"
                or target is None
                or (
                    invocation.get("source_agent_id"),
                    invocation.get("source_thread_id"),
                    invocation.get("scope_thread_id"),
                    invocation.get("root_run_id"),
                )
                != (agent, thread, thread, node.get("run_id"))
            ):
                continue
            remap[node["id"]] = target["id"]
            target["source_refs"] = sorted({*target.get("source_refs", []), node["id"]})
            if node.get("task_id"):
                target["task_id"] = node["task_id"]
                target["attempt_id"] = node.get("attempt_id")
                target["dependencies_known"] = True
        nodes = [node for node in nodes if node["id"] not in remap]
        edges = [
            {
                **edge,
                "from": remap.get(edge["from"], edge["from"]),
                "to": remap.get(edge["to"], edge["to"]),
            }
            for edge in edges
            if remap.get(edge["from"], edge["from"]) != remap.get(edge["to"], edge["to"])
        ]
        # Link only the exact job_start submission receipt. Later status/log/cancel
        # observations do not identify a producer, and ambiguity stays unlinked.
        submissions: dict[tuple[str, str, str], list[str]] = {}
        for node in nodes:
            payload = node.get("details") or {}
            context, job = node.get("context_id"), payload.get("job_id")
            if (
                node["type"] == "tool"
                and payload.get("name") == "job_start"
                and isinstance(context, str)
                and context
                and isinstance(job, str)
                and job
                and payload.get("context_id") == context
                and node.get("status") in {"completed", "accepted"}
            ):
                submissions.setdefault((str(node["run_id"]), context, job), []).append(node["id"])
        for node in nodes:
            payload = node.get("details") or {}
            context, job = node.get("context_id"), payload.get("job_id")
            if (
                node["type"] != "job"
                or not isinstance(context, str)
                or not context
                or not isinstance(job, str)
                or not job
            ):
                continue
            if payload.get("context_id", context) != context:
                continue
            candidates = submissions.get((str(node["run_id"]), context, job), [])
            if len(candidates) == 1:
                edges.append({"from": candidates[0], "to": node["id"], "kind": "contains"})

        for node in nodes:
            if node["type"] == "plan":
                children = [
                    n
                    for n in nodes
                    if n.get("task_id") == node["task_id"]
                    and n.get("run_id") == node["run_id"]
                    and n["type"] != "plan"
                ]
                if children:
                    node["status"] = (
                        "running"
                        if any(
                            n["status"] == "running" and n.get("observed_status") == "current"
                            for n in children
                        )
                        else max(
                            children,
                            key=lambda n: (n.get("created_at", 0), n["updated_at"], n["id"]),
                        )["status"]
                    )

        plan_nodes = {node["id"]: node for node in nodes if node["type"] == "plan"}
        for node in plan_nodes.values():
            if node["status"] != "waiting":
                continue
            dependencies = [
                plan_nodes.get(edge["from"])
                for edge in edges
                if edge["kind"] == "depends_on" and edge["to"] == node["id"]
            ]
            if dependencies and all(
                dependency and dependency["status"] == "completed" for dependency in dependencies
            ):
                node["status"] = "pending"

        active_tasks = {
            tasks[(node["run_id"], node["task_id"])]
            for node in nodes
            if node["type"] != "plan"
            and node.get("task_id")
            and (node.get("run_id"), node["task_id"]) in tasks
            and node["status"] == "running"
            and node.get("observed_status") == "current"
        }

        def running(n: dict[str, Any]) -> bool:
            return (
                n["status"] in {"running", "accepted", "waiting"}
                and n.get("observed_status") != "stale"
            )

        return {
            "nodes": nodes,
            "edges": edges,
            "observed_at": now,
            "source_cursors": {"receipts": max((e["updated_at"] for e in events), default=0)},
            "scope_truncated": page["has_more"] or len(active) > 200,
            "active_scope_truncated": len(active) > 200,
            "next_before": page["next_before"],
            "counts": {
                "subagents": sum(
                    running(n) for n in nodes if n["type"] in {"subagent", "delegation"}
                ),
                "jobs": sum(running(n) for n in nodes if n["type"] == "job"),
                "parallel": len(active_tasks) if tasks else None,
                "completed": sum(
                    n["status"] == "completed"
                    for n in nodes
                    if n["type"] in {"plan", "subagent", "delegation", "job"}
                ),
            },
        }
