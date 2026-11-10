"""Agent authoring uses the same revisions, validation and authority as the editor."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from langgraph.config import get_config

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.workflow_graphs.service import (
    RunControl,
    SaveGraph,
    StartRun,
    WorkflowGraphService,
)


def build_workflow_tools(service: WorkflowGraphService, agent_id: str) -> list[Any]:
    async def workflow_graph(
        operation: str, graph_id: str = "", payload: dict[str, Any] | None = None
    ) -> str:
        """Create and operate durable workflows for iteration or daily tasks.

        Operations: list, get, validate, save, publish, archive, start, runs,
        run, timeline, inspect, control, retry, reconcile, capability, revoke.
        save payload: {revision, definition}; definition has nodes (entry, agent,
        script, condition, event, wait_event, wait_time, fork, join, end), edges
        {id,source,target,port}. New drafts use revision=0. get returns the draft
        and validation issues. validate payload: {definition}. publish/archive
        require {revision}. start requires {request_id,variables?}. Runs pin the
        published version, edits never modify running instances. run/timeline/
        control take payload.run_id; inspect/retry/reconcile take activation_id.
        control.action is pause/resume/cancel; optional max_steps/extra_seconds
        extends a resumed budget. Pause and cancel retain accepted Jobs. Retry
        explicitly authorizes NEW work and may duplicate effects; reconcile first.
        capability returns a private event-start credential, revoke rotates it.
        Bindings are {path:'$.vars.x'}, {path:'$.outputs.node.result.x'},
        {path:'$.event.x'} or {value:literal}, with no executable expressions.
        Agent prompt inputs are data, script argv is static, resolved inputs are
        in OCTOPUS_WORKFLOW_INPUT. Script callback_node injects private
        OCTOPUS_WAKEUP_URL/TOKEN after an event registration node. Agent context
        before: session current/new, history inherit/recent/empty, recent_turns,
        inject or inject_from binding; after: session/context keep/restore.
        New child sessions retain separate archives. Preserve server and expert
        rules; never place secrets in definitions or normal outputs.
        """
        try:
            cfg = get_config().get("configurable") or {}
            owner = int(cfg.get("user") or 0)
            if owner <= 0:
                raise ValueError("workflow requires an authenticated owner")
            user = service.repos.user_repo.get(owner)
            if user is None or user.disabled:
                raise OctopError(ErrorCode.FORBIDDEN, "authenticated active user required")
            if cfg.get("octop_shared_text_scope"):
                raise ValueError("shared text collaboration cannot access workflow resources")
            reads = {"list", "get", "validate", "runs", "run", "timeline", "inspect"}
            execution = cfg.get("octop_execution_context") or {}
            if operation not in reads and {
                cfg.get("work_mode"),
                cfg.get("conversation_mode"),
                execution.get("work_mode"),
            } & {"ask", "plan"}:
                raise ValueError("this mode permits workflow observation only")
            data = dict(payload or {})
            result: Any
            if operation == "list":
                result = service.list(owner)
            elif operation == "get":
                result = service.get(owner, graph_id)
            elif operation == "validate":
                from octop.infra.workflow_graphs.models import GraphDefinition, validate_graph

                result = [
                    issue.model_dump()
                    for issue in validate_graph(GraphDefinition.model_validate(data["definition"]))
                ]
            elif operation == "save":
                definition = dict(data["definition"])
                definition.setdefault("agent_id", agent_id)
                definition.setdefault("origin_thread_id", str(cfg.get("thread_id") or ""))
                source = cfg.get("octop_execution_context") or {}
                definition.setdefault("execution_context_id", str(source.get("context_id") or ""))
                result = service.save(
                    owner,
                    SaveGraph.model_validate(
                        {
                            "graph_id": graph_id,
                            "revision": data["revision"],
                            "definition": definition,
                        }
                    ),
                )
            elif operation == "publish":
                result = service.publish(owner, graph_id, int(data["revision"]))
            elif operation == "archive":
                service.archive(owner, graph_id, int(data["revision"]))
                result = {"archived": True}
            elif operation == "start":
                result = await service.start(owner, graph_id, StartRun.model_validate(data))
            elif operation == "runs":
                result = service.runs(owner, graph_id, 50, 0)
            elif operation == "run":
                result = service.run(owner, data["run_id"])
            elif operation == "timeline":
                result = service.timeline(owner, data["run_id"], 100, int(data.get("offset", 0)))
            elif operation == "inspect":
                result = service.inspect(owner, data["activation_id"])
            elif operation == "control":
                identity = data.pop("run_id")
                result = service.control(owner, identity, RunControl.model_validate(data))
            elif operation == "retry":
                result = service.retry(owner, data["activation_id"])
            elif operation == "reconcile":
                result = await service.runner.reconcile(owner, data["activation_id"])
            elif operation == "cancel_jobs":
                result = await service.runner.cancel_jobs(owner, data["run_id"])
            elif operation in {"capability", "revoke"}:
                result = service.capability(owner, graph_id, revoke=operation == "revoke")
            else:
                raise ValueError("unsupported workflow operation")
            if hasattr(result, "model_dump"):
                result = result.model_dump(mode="json")
            return json.dumps(result, ensure_ascii=False)
        except OctopError as exc:
            return json.dumps(exc.to_envelope(), ensure_ascii=False)
        except (ValueError, TypeError, KeyError) as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    async def workflow_graph_list() -> str:
        """List the authenticated owner's workflow drafts and published revisions."""
        return await workflow_graph("list")

    async def workflow_graph_get(graph_id: str) -> str:
        """Read a workflow definition and validation issues before making changes."""
        return await workflow_graph("get", graph_id)

    async def workflow_graph_save(graph_id: str, revision: int, definition: dict[str, Any]) -> str:
        """Save a declarative Graph with revision checking. Use revision 0 for a new graph."""
        return await workflow_graph(
            "save", graph_id, {"revision": revision, "definition": definition}
        )

    async def workflow_graph_validate(definition: dict[str, Any]) -> str:
        """Validate node types, bindings, connections and fork/join regions without dispatch."""
        return await workflow_graph("validate", payload={"definition": definition})

    async def workflow_graph_publish(graph_id: str, revision: int) -> str:
        """Publish a valid immutable revision for future manual, event and scheduled starts."""
        return await workflow_graph("publish", graph_id, {"revision": revision})

    async def workflow_graph_start(
        graph_id: str, request_id: str, variables: dict[str, Any] | None = None
    ) -> str:
        """Start the published Graph. Reuse request_id on a retry to avoid duplicate runs."""
        return await workflow_graph(
            "start", graph_id, {"request_id": request_id, "variables": variables or {}}
        )

    async def workflow_graph_run_status(run_id: str, offset: int = 0) -> str:
        """Read actual run state and a bounded page of activation receipts."""
        run = json.loads(await workflow_graph("run", payload={"run_id": run_id}))
        timeline = json.loads(
            await workflow_graph("timeline", payload={"run_id": run_id, "offset": offset})
        )
        return json.dumps({"run": run, "timeline": timeline}, ensure_ascii=False)

    async def workflow_graph_control(
        run_id: str, action: str, max_steps: int | None = None, extra_seconds: int | None = None
    ) -> str:
        """Pause/resume/cancel successors; cancel_jobs separately requests cancellation of owned Jobs."""
        return await workflow_graph(
            "cancel_jobs" if action == "cancel_jobs" else "control",
            payload={
                "run_id": run_id,
                "action": action,
                "max_steps": max_steps,
                "extra_seconds": extra_seconds,
            },
        )

    return [
        StructuredTool.from_function(coroutine=func)
        for func in (
            workflow_graph,
            workflow_graph_list,
            workflow_graph_get,
            workflow_graph_save,
            workflow_graph_validate,
            workflow_graph_publish,
            workflow_graph_start,
            workflow_graph_run_status,
            workflow_graph_control,
        )
    ]
