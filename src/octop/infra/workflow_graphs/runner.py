"""Durable activation scheduler. Side effects retain their actual receiver receipts."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import os
import socket
import time
from collections.abc import Callable
from typing import Any

from octop.infra.cron.delivery import CronDeliveryCommand, WorkflowAdmissionDeferred
from octop.infra.cron.origin_target import ensure_pin_session
from octop.infra.devices.jobs import confirmed_stopped, process_identity
from octop.infra.devices.protocol import JOB_ENVIRONMENT_UNSUPPORTED
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.ulid import new_ulid
from octop.infra.workflow_graphs.models import (
    MAX_INPUT_BYTES,
    MAX_OUTPUT_BYTES,
    AgentNode,
    ConditionNode,
    EventNode,
    ForkNode,
    GraphDefinition,
    JoinNode,
    Node,
    ScriptNode,
    WaitEventNode,
    WaitTimeNode,
    bounded_json,
)
from octop.infra.workflow_graphs.planning import (
    before_context,
    completed_state,
    fork_states,
    join_states,
    outgoing,
)
from octop.infra.workflow_graphs.service import StartRun, activation
from octop.infra.workflow_graphs.state import (
    BranchState,
    ConversationState,
    compare,
    inputs,
    resolve,
)

logger = logging.getLogger(__name__)


class WorkflowRunner:
    def __init__(self, service: Any) -> None:
        self.service = service
        self.worker = json.dumps(
            {
                "id": new_ulid(),
                "host": socket.gethostname(),
                "process": process_identity(os.getpid()),
            },
            sort_keys=True,
        )
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self._ticking = False

    @property
    def store(self) -> Any:
        return self.service.store

    async def tick(self) -> None:
        if self._ticking:
            return
        self._ticking = True
        try:
            self.store.expire_leases(time.time())
            for model in self.store.uncertain_models():
                try:
                    worker = json.loads(model["worker_id"])
                except (ValueError, TypeError):
                    continue
                # Only a confirmed dead local controller proves its accepted
                # model request has terminated. External Jobs stay reserved.
                if (
                    worker.get("host") == socket.gethostname()
                    and worker.get("process")
                    and confirmed_stopped(worker["process"])
                ):
                    self.store.release_capacity(model["owner_user_id"], model["id"])
            self.store.enforce_budgets(time.time())
            for row in self.store.due_schedules(time.time()):
                try:
                    await self.service.start(
                        row["owner_user_id"],
                        row["graph_id"],
                        StartRun(request_id=str(row["next_due_at"])),
                        source="schedule",
                        due=row["next_due_at"],
                    )
                except OctopError:
                    graph = GraphDefinition.model_validate_json(row["definition_json"])
                    self.store.blocked_schedule(
                        row["owner_user_id"],
                        row["graph_id"],
                        row["published_revision"],
                        row["next_due_at"],
                        self.service.next_due(graph, time.time()),
                        new_ulid(),
                        "scheduled origin unavailable; admission was blocked",
                    )
                except Exception:
                    self.store.advance_schedule(
                        row["owner_user_id"], row["graph_id"], row["next_due_at"], time.time() + 15
                    )
                    logger.warning("Workflow schedule deferred for %s", row["graph_id"])
            for row in self.store.waiting():
                try:
                    if row["status"] in {"unknown", "superseded"}:
                        evidence = json.loads(row["evidence_json"] or "{}")
                        receipt = self.service.repos.run_event_repo.get(
                            row["owner_user_id"], evidence.get("job_event_id", "")
                        )
                        if receipt and receipt["status"] in {"completed", "failed", "cancelled"}:
                            self.store.release_capacity(row["owner_user_id"], row["id"])
                    else:
                        await self.observe(row)
                    self.store.update_activation(
                        row["owner_user_id"], row["id"], row["status"], {"next_at": time.time() + 2}
                    )
                except (ValueError, KeyError) as exc:
                    graph, node, state = self.load(row)
                    self.error(row, graph, node, state, str(exc)[:500])
                except OctopError as exc:
                    if exc.code in {
                        ErrorCode.FORBIDDEN,
                        ErrorCode.NOT_FOUND,
                        ErrorCode.USER_DISABLED,
                    }:
                        graph, node, state = self.load(row)
                        self.error(
                            row,
                            graph,
                            node,
                            state,
                            "workflow origin unavailable",
                            unknown=row["status"] == "waiting_job",
                        )
                    else:
                        self.store.update_activation(
                            row["owner_user_id"],
                            row["id"],
                            row["status"],
                            {"next_at": time.time() + 15},
                        )
                except Exception:
                    # Observation is read only. Transient device loss must not fail or replay a Job.
                    self.store.update_activation(
                        row["owner_user_id"],
                        row["id"],
                        row["status"],
                        {"next_at": time.time() + 15},
                    )
                    logger.warning("Workflow receipt observation deferred for %s", row["id"])
            for row in self.store.ready(
                limit=max(0, 128 - len(self.tasks)), exclude=tuple(self.tasks)
            ):
                task = asyncio.create_task(self.execute(row))
                self.tasks[row["id"]] = task

                def remove(_task: asyncio.Task[None], key: str = row["id"]) -> None:
                    self.tasks.pop(key, None)

                task.add_done_callback(remove)
        finally:
            self._ticking = False

    async def shutdown(self) -> None:
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def load(self, row: dict[str, Any]) -> tuple[GraphDefinition, Node, BranchState]:
        graph = self.service.definition(
            row["owner_user_id"], self.service.run(row["owner_user_id"], row["run_id"])
        )
        node = next(item for item in graph.nodes if item.id == row["node_id"])
        return graph, node, BranchState.model_validate_json(row["token_json"])

    async def heartbeat(self, owner: int, identity: str) -> None:
        while True:
            await asyncio.sleep(20)
            if not self.store.renew(owner, identity, self.worker, time.time()):
                return

    def children(
        self,
        graph: GraphDefinition,
        node: Node,
        state: BranchState,
        parent: str,
        port: str = "next",
    ) -> list[dict[str, Any]]:
        nodes = {item.id: item for item in graph.nodes}
        edges = outgoing(graph, node.id, port)
        branches = fork_states(node, state, parent, edges) if isinstance(node, ForkNode) else {}
        return [
            activation(nodes[edge.target], branches.get(edge.id, state), parent, edge.id)
            for edge in edges
        ]

    def complete(
        self,
        row: dict[str, Any],
        graph: GraphDefinition,
        node: Node,
        state: BranchState,
        output: dict[str, Any],
        *,
        port: str = "next",
        executed: ConversationState | None = None,
        expected: str | None = None,
    ) -> bool:
        encoded = bounded_json(output, MAX_OUTPUT_BYTES, "node output")
        after = completed_state(node, state, output, executed)
        current = expected or row["status"]
        return bool(
            self.store.finish(
                row["owner_user_id"],
                row["id"],
                current,
                output=encoded,
                after=after.bounded(),
                children=self.children(graph, node, after, row["id"], port),
                worker=self.worker if current == "running" else None,
            )
        )

    def error(
        self,
        row: dict[str, Any],
        graph: GraphDefinition,
        node: Node,
        state: BranchState,
        message: str,
        *,
        unknown: bool = False,
    ) -> None:
        if row["status"] == "ready":
            # Failed preflight/error routes are still activation attempts.
            # Otherwise an error-edge loop could avoid the step budget.
            if not self.store.claim(row["owner_user_id"], row["id"], self.worker, time.time()):
                return
            row["status"] = "running"
        if isinstance(node, JoinNode) and row["status"] == "waiting_join":
            arrivals = self.store.join_arrivals(
                row["owner_user_id"], row["run_id"], node.id, row["group_id"]
            )
            fork = self.store.activation(row["owner_user_id"], row["group_id"])
            if fork and fork["after_json"]:
                state = BranchState.model_validate_json(fork["after_json"])
                state.outputs[node.id] = {"error": message}
                self.store.fail_join(
                    row["owner_user_id"],
                    [item["id"] for item in arrivals],
                    message,
                    self.children(graph, node, state, row["id"], "error"),
                )
                return
        state = state.clone()
        state.outputs[node.id] = {"error": message}
        try:
            children = self.children(graph, node, state, row["id"], "error") if not unknown else []
        except ValueError:
            children = []
        self.store.fail(
            row["owner_user_id"],
            row["id"],
            row["status"],
            message,
            unknown=unknown,
            worker=self.worker if row["status"] == "running" else None,
            children=children,
        )

    async def execute(self, row: dict[str, Any]) -> None:
        owner = row["owner_user_id"]
        heartbeat: asyncio.Task[None] | None = None
        graph: GraphDefinition | None = None
        dispatched = False
        submitted = False
        try:
            graph, node, state = self.load(row)
            self.service.scope(owner, graph)
            self.service.conversation(
                owner, state.conversation.agent_id, state.conversation.thread_id
            )
            values = inputs(node.inputs, state)
            encoded = bounded_json(values, MAX_INPUT_BYTES, "node inputs")

            def admit() -> bool:
                nonlocal heartbeat, dispatched
                self.service.scope(owner, graph)
                if not self.store.claim(owner, row["id"], self.worker, time.time()):
                    return False
                row["status"] = "running"
                dispatched = True
                self.store.update_activation(
                    owner,
                    row["id"],
                    "running",
                    {"input_json": encoded, "before_json": state.conversation.model_dump_json()},
                    worker=self.worker,
                )
                heartbeat = asyncio.create_task(self.heartbeat(owner, row["id"]))
                return True

            def mark_submitted() -> None:
                nonlocal submitted
                if not self.store.owns_lease(owner, row["id"], self.worker, time.time()):
                    raise ValueError("workflow dispatch lease was lost before submission")
                submitted = True

            if isinstance(node, AgentNode):
                agent = node.agent_id or state.conversation.agent_id
                thread = state.conversation.thread_id
                if node.context.before.session == "new":
                    thread = await self.service.thread(owner, agent, "graph_" + row["id"])
                executed = before_context(node, state, agent, thread)
                context_id = graph.execution_context_id
                mode = (
                    str(self.service.execution.get(owner, context_id).work_mode)
                    if context_id
                    else "ask"
                )
                before = executed.model_dump_json()

                def agent_admit() -> bool:
                    if not admit():
                        return False
                    mark_submitted()
                    return bool(
                        self.store.update_activation(
                            owner,
                            row["id"],
                            "running",
                            {
                                "before_json": before,
                                "evidence_json": json.dumps(
                                    {"delivery_id": row["id"], "context_id": context_id}
                                ),
                            },
                            worker=self.worker,
                        )
                    )

                session = ensure_pin_session(
                    session_repo=self.service.repos.session_repo,
                    thread_id=thread,
                    agent_id=agent,
                    user_id=owner,
                )
                command = CronDeliveryCommand(
                    cron_id="graph-" + row["run_id"],
                    cron_name=node.label,
                    agent_id=agent,
                    user_id=owner,
                    session_key=session.session_key,
                    prompt=node.prompt + "\n\n[Workflow node input data]\n" + encoded,
                    fresh_thread=False,
                    task_type="agent",
                    model=node.model or None,
                    mcp_servers=(),
                    task_run_id=row["id"],
                    reason="workflow",
                    origin_thread_id=thread,
                    delivery_id=row["id"],
                    source_kind="workflow",
                    on_admission=agent_admit,
                    workflow_context={
                        "run_id": row["run_id"],
                        "activation_id": row["id"],
                        "worker": self.worker,
                        "recipe": executed.recipe.model_dump(),
                    },
                    workflow_execution_context_id=context_id,
                    workflow_work_mode=mode,
                )
                # Timeout begins on dispatch, not while queued behind a busy conversation.
                delivery_task = asyncio.create_task(self.service.delivery.deliver(command))
                try:
                    while not delivery_task.done() and not dispatched:
                        await asyncio.wait({delivery_task}, timeout=0.2)
                    text = await asyncio.wait_for(delivery_task, node.timeout_seconds)
                finally:
                    if not delivery_task.done():
                        delivery_task.cancel()
                        await asyncio.gather(delivery_task, return_exceptions=True)
                self.store.record_evidence(
                    owner,
                    row["id"],
                    self.worker,
                    json.dumps(
                        {
                            "delivery_id": row["id"],
                            "context_id": context_id,
                            "text": text.encode("utf-8")[:32768].decode("utf-8", errors="ignore"),
                            "text_truncated": len(text.encode("utf-8")) > 32768,
                        }
                    ),
                )
                try:
                    self.complete(
                        row,
                        graph,
                        node,
                        state,
                        self.output(
                            text, node.output_mode, {"delivery_id": row["id"], "thread_id": thread}
                        ),
                        executed=executed,
                    )
                except ValueError as exc:
                    self.error(row, graph, node, state, str(exc)[:500])
                return
            if not admit():
                return
            if isinstance(node, ScriptNode):
                context_id, _ = self.execution_context(
                    owner,
                    node.execution_context_id or graph.execution_context_id,
                    state.conversation,
                    row["id"],
                )
                if not context_id:
                    raise ValueError("script requires an explicit execution source")
                self.store.update_activation(
                    owner,
                    row["id"],
                    "running",
                    {
                        "before_json": state.conversation.model_dump_json(),
                        "evidence_json": json.dumps({"context_id": context_id}),
                    },
                    worker=self.worker,
                )
                result = await self.submit(
                    row, graph, node, state, context_id, encoded, mark_submitted
                )
                evidence = json.dumps(
                    {
                        "context_id": context_id,
                        "job_id": result["job_id"],
                        "job_event_id": f"job:{result.get('context_id') or context_id}:{result['job_id']}",
                    }
                )
                self.store.record_evidence(owner, row["id"], self.worker, evidence)
                self.store.update_activation(
                    owner,
                    row["id"],
                    "running",
                    {"status": "waiting_job", "lease_until": None},
                    worker=self.worker,
                )
            elif isinstance(node, EventNode):
                hook = self.service.hooks.register(
                    owner,
                    state.conversation.agent_id,
                    state.conversation.thread_id,
                    title=node.label,
                    event_type=node.event_type,
                    purpose=node.purpose or node.label,
                    idempotency_key="graph-" + row["id"],
                    expires_in=node.expires_in,
                    delivery_mode="signal",
                )
                self.complete(
                    row,
                    graph,
                    node,
                    state,
                    {
                        key: hook[key]
                        for key in ("hook_id", "callback_url", "event_type", "expires_at")
                    },
                )
            elif isinstance(node, WaitEventNode):
                event = state.outputs.get(node.event_node, {})
                if not event.get("hook_id"):
                    raise ValueError("event registration is unavailable on this branch")
                self.store.update_activation(
                    owner,
                    row["id"],
                    "running",
                    {
                        "status": "waiting_event",
                        "evidence_json": json.dumps({"hook_id": event["hook_id"]}),
                        "lease_until": None,
                    },
                    worker=self.worker,
                )
            elif isinstance(node, WaitTimeNode):
                self.store.update_activation(
                    owner,
                    row["id"],
                    "running",
                    {
                        "status": "waiting_time",
                        "next_at": time.time() + node.seconds,
                        "lease_until": None,
                    },
                    worker=self.worker,
                )
            elif isinstance(node, JoinNode):
                if not state.forks or state.forks[-1].join_id != node.id:
                    raise ValueError("join is outside its fork group")
                self.store.arrive_join(owner, row["id"], self.worker)
            elif isinstance(node, ConditionNode):
                matched = compare(
                    node.operator, resolve(node.left, state), resolve(node.right, state)
                )
                self.complete(
                    row,
                    graph,
                    node,
                    state,
                    {"result": matched},
                    port="true" if matched else "false",
                )
            else:
                self.complete(row, graph, node, state, {"result": node.kind})
        except WorkflowAdmissionDeferred:
            pass
        except asyncio.CancelledError:
            if dispatched and graph is not None:
                self.error(
                    row,
                    graph,
                    node,
                    state,
                    "worker stopped; reconcile its receipt before retrying",
                    unknown=submitted,
                )
            raise
        except Exception as exc:
            if graph is not None:
                # Never infer a failed side effect from an absent response.
                message = f"node execution failed ({type(exc).__name__})"
                if isinstance(exc, OctopError) and exc.message == JOB_ENVIRONMENT_UNSUPPORTED:
                    message = JOB_ENVIRONMENT_UNSUPPORTED
                self.error(
                    row,
                    graph,
                    node,
                    state,
                    message,
                    unknown=submitted,
                )
            logger.warning("Workflow activation stopped: %s (%s)", row["id"], type(exc).__name__)
        finally:
            if dispatched and graph is not None and (node.kind == "agent" or not submitted):
                # Delivery cancellation/termination was awaited above. A lost
                # lease alone never releases this request's reservation.
                self.store.release_capacity(owner, row["id"])
            if heartbeat is not None:
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat

    def execution_context(
        self, owner: int, source: str, conversation: ConversationState, identity: str
    ) -> tuple[str, str]:
        if not source:
            return "", "ask"
        context = self.service.execution.for_run(
            owner,
            source,
            agent_id=conversation.agent_id,
            thread_id=conversation.thread_id,
            run_id=identity,
        )
        return str(context.context_id), str(context.work_mode)

    async def submit(
        self,
        row: dict[str, Any],
        graph: GraphDefinition,
        node: ScriptNode,
        state: BranchState,
        context_id: str,
        encoded: str,
        mark_submitted: Callable[[], None],
    ) -> dict[str, Any]:
        env = {**node.env, "OCTOPUS_WORKFLOW_INPUT": encoded}
        if node.callback_node:
            hook_id = str(state.outputs.get(node.callback_node, {}).get("hook_id") or "")
            hook = self.service.hooks.events.wakeup_hook(hook_id)
            if (
                not hook
                or hook["owner_user_id"] != row["owner_user_id"]
                or hook["payload"].get("delivery_mode") != "signal"
            ):
                raise ValueError("callback registration unavailable")
            self.service.hooks._scope(hook)
            env.update(
                OCTOPUS_WAKEUP_TOKEN=self.service.hooks._token(hook),
                OCTOPUS_WAKEUP_URL=str(state.outputs[node.callback_node]["callback_url"]),
            )
        bounded_json(env, 128 * 1024, "script environment")
        result = await self.service.execution.call(
            row["owner_user_id"],
            context_id,
            "jobs.start",
            {
                "argv": node.argv,
                **({"cwd": node.cwd} if node.cwd else {}),
                "env": env,
                "idempotency_key": "graph-" + row["id"],
                "title": node.label,
                "notify_on_exit": False,
            },
            actor_agent_id=state.conversation.agent_id,
            on_dispatch=mark_submitted,
        )
        return dict(result["result"])

    @staticmethod
    def output(
        text: str, mode: str, evidence: dict[str, Any], *, truncated: bool = False
    ) -> dict[str, Any]:
        if mode == "json":
            if truncated:
                raise ValueError("structured output was truncated")
            result = json.loads(text)
        else:
            result = None
        # Explicit bounded text preview leaves room for receipt metadata.
        preview = text.encode("utf-8")[:24000].decode("utf-8", errors="ignore")
        output = {
            "text": preview,
            "text_truncated": truncated or preview != text,
            "evidence": evidence,
        }
        if mode == "json":
            output["result"] = result
        bounded_json(output, MAX_OUTPUT_BYTES, "node output")
        return output

    async def observe(self, row: dict[str, Any]) -> bool:
        owner = row["owner_user_id"]
        graph, node, state = self.load(row)
        self.service.scope(owner, graph)
        evidence = json.loads(row["evidence_json"] or "{}")
        status = row["status"]
        if status == "waiting_time":
            return self.complete(row, graph, node, state, {"result": "timer", "at": row["next_at"]})
        if status == "waiting_event":
            hook = self.service.hooks.events.wakeup_hook(evidence["hook_id"])
            if not hook or hook["owner_user_id"] != owner:
                raise ValueError("signal unavailable")
            if hook["status"] in {"cancelled", "blocked"} or (
                hook["status"] == "waiting" and hook["payload"]["expires_at"] <= time.time()
            ):
                self.error(row, graph, node, state, "event expired or was revoked")
                return False
            if hook["status"] not in {"queued", "completed"}:
                return False
            consumer = hook["payload"].get("graph_consumer")
            if consumer and consumer != row["id"]:
                raise ValueError(
                    "this signal was already consumed; register a fresh event for each iteration"
                )
            if not consumer:
                claimed = {**hook["payload"], "graph_consumer": row["id"]}
                if not self.service.hooks.events.compare_payload(
                    owner,
                    hook["event_id"],
                    hook["payload"],
                    claimed,
                    hook["status"],
                    expected_status=hook["status"],
                ):
                    return False
                hook["payload"] = claimed
            state.event = hook["payload"].get("data")
            finished = self.complete(
                row, graph, node, state, {"result": state.event, "hook_id": evidence["hook_id"]}
            )
            if finished:
                self.service.hooks.events.compare_payload(
                    owner,
                    hook["event_id"],
                    hook["payload"],
                    hook["payload"],
                    "completed",
                    expected_status="queued",
                )
            return finished
        if status == "waiting_join" and isinstance(node, JoinNode):
            rows = self.store.join_arrivals(owner, row["run_id"], node.id, row["group_id"])
            if not state.forks or len(rows) != len(state.forks[-1].branches):
                return False
            fork = self.store.activation(owner, row["group_id"])
            if not fork or not fork["after_json"]:
                return False
            after, output = join_states(
                node,
                BranchState.model_validate_json(fork["after_json"]),
                {
                    item["branch_id"]: BranchState.model_validate_json(item["token_json"])
                    for item in rows
                },
            )
            return bool(
                self.store.finish_join(
                    owner,
                    [item["id"] for item in rows],
                    output=bounded_json(output, MAX_OUTPUT_BYTES, "join output"),
                    after=after.bounded(),
                    children=self.children(graph, node, after, row["id"]),
                )
            )
        if status in {"waiting_job", "unknown"} and isinstance(node, ScriptNode):
            if not evidence.get("job_event_id"):
                return False
            receipt = self.service.repos.run_event_repo.get(owner, evidence["job_event_id"])
            if not receipt or receipt["status"] not in {"completed", "failed", "cancelled"}:
                return False
            if receipt["status"] != "completed":
                self.error(row, graph, node, state, "script " + receipt["status"])
                return False
            response = await self.service.execution.call(
                owner,
                evidence["context_id"],
                "jobs.logs",
                {"job_id": evidence["job_id"], "offset": 0, "length": 32769},
                actor_agent_id=state.conversation.agent_id,
            )
            logs = response["result"]
            text = base64.b64decode(logs["data_b64"]).decode("utf-8", errors="replace")
            try:
                return self.complete(
                    row,
                    graph,
                    node,
                    state,
                    self.output(
                        text,
                        node.output_mode,
                        evidence,
                        truncated=bool(logs.get("truncated"))
                        or int(logs.get("next_offset", 0)) >= 32769,
                    ),
                )
            except ValueError as exc:
                self.error(row, graph, node, state, str(exc)[:500])
        if status == "unknown" and isinstance(node, AgentNode) and evidence.get("text") is not None:
            executed = ConversationState.model_validate_json(row["before_json"])
            return self.complete(
                row,
                graph,
                node,
                state,
                self.output(
                    evidence["text"],
                    node.output_mode,
                    {"delivery_id": row["id"]},
                    truncated=bool(evidence.get("text_truncated")),
                ),
                executed=executed,
            )
        return False

    async def reconcile(self, owner: int, identity: str) -> dict[str, Any]:
        row = self.store.activation(owner, identity)
        if not row or row["status"] not in {"unknown", "waiting_job"}:
            raise ValueError("activation does not require reconciliation")
        graph, node, state = self.load(row)
        self.service.scope(owner, graph)
        evidence = json.loads(row["evidence_json"] or "{}")
        if isinstance(node, ScriptNode) and not evidence.get("job_id"):
            # Reconciliation never submits a command. The receiver's Job ID is
            # derived from the original dispatch key even if its response was lost.
            job_id = hashlib.sha256(("graph-" + identity).encode()).hexdigest()[:32]
            response = await self.service.execution.call(
                owner,
                evidence["context_id"],
                "jobs.status",
                {"job_id": job_id},
                actor_agent_id=state.conversation.agent_id,
            )
            result = response["result"]
            evidence.update(
                job_id=result["job_id"],
                job_event_id=f"job:{result.get('context_id') or evidence['context_id']}:{result['job_id']}",
            )
            self.store.record_evidence(owner, identity, row["worker_id"], json.dumps(evidence))
            row["evidence_json"] = json.dumps(evidence)
        await self.observe(row)
        return dict(self.service.inspect(owner, identity))

    async def cancel_jobs(self, owner: int, run_id: str) -> dict[str, Any]:
        self.service.run(owner, run_id)
        self.store.control(owner, run_id, "cancel")
        results = []
        for row in self.store.activations(owner, run_id):
            if row["kind"] != "script" or not row["capacity_held"]:
                continue
            evidence = json.loads(row["evidence_json"] or "{}")
            if not evidence.get("job_id"):
                results.append(
                    {
                        "activation_id": row["id"],
                        "status": "unknown",
                        "error": "reconcile the original submission first",
                    }
                )
                continue
            try:
                _, _, state = self.load(row)
                response = await self.service.execution.call(
                    owner,
                    evidence["context_id"],
                    "jobs.cancel",
                    {"job_id": evidence["job_id"]},
                    actor_agent_id=state.conversation.agent_id,
                )
                results.append({"activation_id": row["id"], "status": response["result"]["status"]})
            except Exception as exc:
                results.append(
                    {"activation_id": row["id"], "status": "unknown", "error": type(exc).__name__}
                )
        return {"run": self.service.run(owner, run_id), "jobs": results}
