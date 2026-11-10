"""Shared authoring, admission and inspection boundary for users and Agents."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from pydantic import Field

from octop.infra.db.repos.workflow_graphs import WorkflowGraphRepo
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.execution.wakeup_hooks import WakeupHookService
from octop.infra.utils.ulid import new_ulid
from octop.infra.workflow_graphs.models import (
    MAX_INITIAL_BYTES,
    AgentNode,
    GraphDefinition,
    Identifier,
    Issue,
    Model,
    Node,
    ScriptNode,
    bounded_json,
    validate_graph,
)
from octop.infra.workflow_graphs.state import BranchState, ConversationState


class GraphView(Model):
    graph_id: str
    revision: int
    published_revision: int | None
    definition: GraphDefinition
    issues: list[Issue]
    archived: bool = False


class SaveGraph(Model):
    graph_id: Identifier
    revision: int = Field(ge=0)
    definition: GraphDefinition


class StartRun(Model):
    request_id: str = Field(min_length=1, max_length=160)
    variables: dict[str, Any] = Field(default_factory=dict)


class RunControl(Model):
    action: str
    max_steps: int | None = Field(default=None, ge=1, le=1000)
    extra_seconds: int | None = Field(default=None, ge=60, le=2592000)


class Page(Model):
    items: list[dict[str, Any]]
    total: int


def missing() -> OctopError:
    return OctopError(ErrorCode.NOT_FOUND, "workflow resource unavailable")


def conflict() -> OctopError:
    return OctopError(ErrorCode.WORKFLOW_CONFLICT, "workflow changed; reload before editing")


def activation(node: Node, state: BranchState, parent: str = "", edge: str = "") -> dict[str, Any]:
    frame = state.forks[-1] if state.forks else None
    return {
        "id": new_ulid(),
        "node_id": node.id,
        "kind": node.kind,
        "token_json": state.bounded(),
        "parent_id": parent,
        "incoming_edge": edge,
        "group_id": frame.group_id if frame else "",
        "branch_id": frame.branch if frame else "",
    }


class WorkflowGraphService:
    def __init__(
        self,
        *,
        repos: RepoBundle,
        registry: Any,
        gateway: Any,
        delivery: Any,
        execution: Any,
        timezone: str,
    ) -> None:
        self.repos = repos
        self.store = WorkflowGraphRepo(repos.db)
        self.registry, self.gateway, self.delivery = registry, gateway, delivery
        self.execution, self.timezone = execution, timezone
        self.hooks = WakeupHookService(execution)
        from octop.infra.workflow_graphs.runner import WorkflowRunner

        self.runner = WorkflowRunner(self)

    def replace_repos(self, repos: RepoBundle) -> None:
        self.repos, self.store = repos, WorkflowGraphRepo(repos.db)
        self.hooks = WakeupHookService(self.execution)

    def scope(self, owner: int, graph: GraphDefinition) -> None:
        user = self.repos.user_repo.get(owner)
        if not user or user.disabled:
            raise missing()
        for agent in {
            graph.agent_id,
            *(n.agent_id for n in graph.nodes if isinstance(n, AgentNode)),
        } - {""}:
            row = self.repos.agent_repo.get(agent)
            if row is None or row.user_id != owner:
                raise missing()
        if graph.origin_thread_id:
            self.conversation(owner, graph.agent_id, graph.origin_thread_id)
        for context in {
            graph.execution_context_id,
            *(n.execution_context_id for n in graph.nodes if isinstance(n, ScriptNode)),
        } - {""}:
            self.execution.get(owner, context)

    def conversation(self, owner: int, agent: str, thread: str) -> None:
        row = self.repos.thread_repo.get(thread)
        if row is None or (row.user_id, row.agent_id) != (owner, agent):
            raise missing()

    def get(self, owner: int, graph_id: str) -> GraphView:
        row = self.store.get(owner, graph_id)
        if row is None:
            raise missing()
        graph = GraphDefinition.model_validate_json(row["draft_json"])
        return GraphView(
            graph_id=graph_id,
            revision=row["revision"],
            published_revision=row["published_revision"],
            definition=graph,
            issues=validate_graph(graph),
            archived=row["archived_at"] is not None,
        )

    def list(self, owner: int, limit: int = 50, offset: int = 0) -> Page:
        rows, total = self.store.list_graphs(owner, limit, offset)
        return Page(
            items=[
                {
                    key: row[key]
                    for key in ("graph_id", "name", "revision", "published_revision", "updated_at")
                }
                for row in rows
            ],
            total=total,
        )

    def save(self, owner: int, command: SaveGraph) -> GraphView:
        self.scope(owner, command.definition)
        if not self.store.save(
            owner,
            command.graph_id,
            command.revision,
            command.definition.name,
            command.definition.model_dump_json(exclude_unset=True),
        ):
            raise conflict()
        return self.get(owner, command.graph_id)

    def next_due(self, graph: GraphDefinition, now: float) -> float | None:
        schedule = graph.schedule
        if schedule is None or not schedule.enabled:
            return None
        zone = ZoneInfo(schedule.timezone or self.timezone)
        following = CronTrigger.from_crontab(schedule.cron, timezone=zone).get_next_fire_time(
            None, datetime.fromtimestamp(now + 1, zone)
        )
        return following.timestamp() if following else None

    def publish(self, owner: int, graph_id: str, revision: int) -> GraphView:
        view = self.get(owner, graph_id)
        self.scope(owner, view.definition)
        if view.issues:
            raise ValueError("; ".join(issue.message for issue in view.issues))
        if not self.store.publish(
            owner, graph_id, revision, self.next_due(view.definition, time.time())
        ):
            raise conflict()
        return self.get(owner, graph_id)

    def archive(self, owner: int, graph_id: str, revision: int) -> None:
        if not self.store.archive(owner, graph_id, revision):
            raise conflict()

    def definition(self, owner: int, run: dict[str, Any]) -> GraphDefinition:
        row = self.store.version(owner, run["graph_id"], run["version"])
        if not row:
            raise missing()
        return GraphDefinition.model_validate_json(row["definition_json"])

    def published_version(self, owner: int, graph_id: str, revision: int) -> GraphDefinition:
        row = self.store.version(owner, graph_id, revision)
        if not row:
            raise missing()
        return GraphDefinition.model_validate_json(row["definition_json"])

    async def thread(self, owner: int, agent: str, key: str) -> str:
        return str(
            await self.gateway.thread_registry.get_or_create_by_key(
                session_key=f"{agent}:dashboard:{owner}:{key}",
                agent_id=agent,
                user_id=owner,
                channel_type="dashboard",
            )
        )

    async def start(
        self,
        owner: int,
        graph_id: str,
        command: StartRun,
        *,
        event: Any = None,
        source: str = "manual",
        due: float | None = None,
    ) -> dict[str, Any]:
        row = self.store.get(owner, graph_id)
        if row is None or row["archived_at"] is not None or row["published_revision"] is None:
            raise missing()
        version = int(row["published_revision"])
        stored = self.store.version(owner, graph_id, version)
        assert stored is not None
        graph = GraphDefinition.model_validate_json(stored["definition_json"])
        self.scope(owner, graph)
        data = bounded_json(
            {"variables": command.variables, "event": event}, MAX_INITIAL_BYTES, "initial input"
        )
        canonical = json.dumps(
            json.loads(data),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
        key = source + ":" + command.request_id
        prior = self.store.run_by_key(owner, graph_id, key)
        if prior:
            if prior["request_fingerprint"] != fingerprint:
                raise ValueError("request ID reused with different inputs")
            return self.run(owner, prior["id"])
        run_id = new_ulid()
        thread = graph.origin_thread_id or await self.thread(
            owner, graph.agent_id, "graph_" + run_id
        )
        state = BranchState(
            variables={**graph.initial_variables, **command.variables},
            event=event,
            conversation=ConversationState(agent_id=graph.agent_id, thread_id=thread),
        )
        entry = next(node for node in graph.nodes if node.kind == "entry")
        identity, _ = self.store.create_run(
            owner=owner,
            graph_id=graph_id,
            version=version,
            run_id=run_id,
            key=key,
            fingerprint=fingerprint,
            initial=data,
            max_steps=graph.limits.max_steps,
            max_parallel=graph.limits.max_parallel,
            deadline=time.time() + graph.limits.max_seconds,
            entry=activation(entry, state),
            expected_published=version,
            schedule_due=due,
            next_due=self.next_due(graph, time.time()),
            skip_if_active=source == "schedule"
            and bool(graph.schedule and graph.schedule.overlap == "skip"),
        )
        return self.run(owner, identity)

    def run(self, owner: int, run_id: str) -> dict[str, Any]:
        row = self.store.run(owner, run_id)
        if row is None:
            raise missing()
        result = {
            key: value
            for key, value in row.items()
            if key not in {"initial_json", "request_fingerprint"}
        }
        result["node_states"] = self.store.latest_nodes(owner, run_id)
        return result

    def runs(self, owner: int, graph_id: str, limit: int, offset: int) -> Page:
        self.get(owner, graph_id)
        rows, total = self.store.list_runs(owner, graph_id, limit, offset)
        return Page(items=[self.run(owner, row["id"]) for row in rows], total=total)

    def timeline(self, owner: int, run_id: str, limit: int, offset: int) -> Page:
        self.run(owner, run_id)
        rows, total = self.store.activation_page(owner, run_id, limit, offset)
        return Page(items=rows, total=total)

    def inspect(self, owner: int, activation_id: str) -> dict[str, Any]:
        row = self.store.activation(owner, activation_id)
        if row is None:
            raise missing()
        result = {
            key: value
            for key, value in row.items()
            if not key.endswith("_json") and key not in {"worker_id", "lease_until"}
        }
        for key in ("input", "output", "before", "after", "evidence"):
            result[key] = json.loads(row[key + "_json"]) if row[key + "_json"] else None
        for key in ("before", "after"):
            if not result[key]:
                result[key] = None
        public = re.sub(
            r"\b(?:owh_[0-9a-f]{64}|og_[0-9]+_[0-9a-f]{64})\b",
            "[redacted credential]",
            json.dumps(result, ensure_ascii=False),
        )
        return dict(json.loads(public))

    def control(self, owner: int, run_id: str, command: RunControl) -> dict[str, Any]:
        self.run(owner, run_id)
        if not self.store.control(
            owner,
            run_id,
            command.action,
            max_steps=command.max_steps,
            deadline=time.time() + command.extra_seconds if command.extra_seconds else None,
        ):
            raise ValueError(
                "run cannot perform this action; reconcile unknown work or extend its budget"
            )
        return self.run(owner, run_id)

    def retry(self, owner: int, activation_id: str) -> dict[str, Any]:
        row = self.store.activation(owner, activation_id)
        if not row:
            raise missing()
        if row["kind"] == "join" and row["status"] == "failed":
            raise ValueError(
                "a failed join cannot be retried alone; correct its merge mappings and start a new published run"
            )
        graph = self.definition(owner, self.run(owner, row["run_id"]))
        self.scope(owner, graph)
        node = next(node for node in graph.nodes if node.id == row["node_id"])
        replacement = activation(
            node,
            BranchState.model_validate_json(row["token_json"]),
            row["parent_id"],
            row["incoming_edge"],
        )
        if not self.store.retry(owner, activation_id, replacement):
            raise ValueError("activation cannot be retried")
        return self.run(owner, row["run_id"])

    def check_worker(self, cfg: dict[str, Any], agent: str, now: float) -> None:
        from langgraph.config import get_config

        current = get_config().get("configurable") or {}
        owner = int(current.get("user") or 0)
        row = self.store.activation(owner, str(cfg.get("activation_id", "")))
        if (
            not row
            or row["run_id"] != cfg.get("run_id")
            or not self.store.owns_lease(owner, row["id"], str(cfg.get("worker", "")), now)
        ):
            raise ValueError("workflow worker no longer owns this activation")
        before = json.loads(row["before_json"] or "{}")
        if before.get("agent_id") != agent or before.get("thread_id") != current.get("thread_id"):
            raise missing()
        graph = self.definition(owner, self.run(owner, row["run_id"]))
        self.scope(owner, graph)

    def _capability(self, owner: int, graph_id: str, generation: int) -> str:
        secret = self.repos.secret_repo.get("jwt")
        if not secret:
            raise ValueError("callback credentials unavailable")
        digest = hmac.new(
            secret, f"graph:{owner}:{graph_id}:{generation}".encode(), hashlib.sha256
        ).hexdigest()
        return f"og_{owner}_{digest}"

    def capability(self, owner: int, graph_id: str, revoke: bool = False) -> dict[str, str]:
        from octop.infra.devices.protocol import resolve_default_device_server

        row = self.store.get(owner, graph_id)
        if not row or row["archived_at"] is not None:
            raise missing()
        generation = row["trigger_generation"]
        if revoke:
            if not self.store.rotate_capability(owner, graph_id, generation):
                raise conflict()
            generation += 1
        return {
            "token": self._capability(owner, graph_id, generation),
            "callback_url": resolve_default_device_server().rstrip("/")
            + f"/api/workflow-graphs/{graph_id}/events",
        }

    async def fire(self, graph_id: str, token: str, event_id: str, data: Any) -> dict[str, Any]:
        try:
            owner = int(token.split("_", 2)[1])
        except (ValueError, IndexError) as exc:
            raise OctopError(ErrorCode.AUTH_FAILED, "invalid graph credential") from exc
        row = self.store.get(owner, graph_id)
        if not row or not hmac.compare_digest(
            token, self._capability(owner, graph_id, row["trigger_generation"])
        ):
            raise OctopError(ErrorCode.AUTH_FAILED, "invalid graph credential")
        version = self.store.version(owner, graph_id, row["published_revision"] or 0)
        if (
            not version
            or not GraphDefinition.model_validate_json(version["definition_json"]).event_start
        ):
            raise missing()
        bounded_json(data, 8192, "event data")
        return await self.start(
            owner, graph_id, StartRun(request_id=event_id), event=data, source="event"
        )

    async def tick(self) -> None:
        await self.runner.tick()

    def recover(self) -> None:
        now = time.time()
        while rows := self.store.due_schedules(now):
            for row in rows:
                graph = GraphDefinition.model_validate_json(row["definition_json"])
                self.store.advance_schedule(
                    row["owner_user_id"],
                    row["graph_id"],
                    row["next_due_at"],
                    self.next_due(graph, now),
                )

    async def shutdown(self) -> None:
        await self.runner.shutdown()
