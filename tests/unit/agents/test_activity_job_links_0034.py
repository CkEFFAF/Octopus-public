"""Explicit persisted tool/Job identity joins; no title/time-based association."""

from __future__ import annotations

from typing import Any

from tests.unit.agents.test_collaboration_resources import call
from tests.unit.agents.test_collaboration_resources import rig as link_rig

from octop.infra.agents.teams.collaboration import CollaborationService
from octop.infra.db.repos.run_events import RunEventRepo
from octop.infra.execution.activity import ActivityService, WorkPlan

rig = link_rig


def receipt(
    rig: Any,
    identity: str,
    kind: str,
    context: str,
    job: str,
    *,
    run: str = "root-run",
    thread: str = "root",
    agent: str = "parent",
) -> None:
    RunEventRepo(rig.repos.db).save(
        event_id=identity,
        owner=rig.owner,
        agent_id=agent,
        thread_id=thread,
        run_id=run,
        context_id=context,
        kind=kind,
        status="running" if kind == "job" else "completed",
        payload={"name": "job_start", "context_id": context, "job_id": job},
    )


def snapshot(rig: Any) -> dict[str, Any]:
    rig.manager.steering_status = lambda agent, thread: None
    return ActivityService(rig.manager).snapshot(rig.owner, "parent", "root")


def test_two_parallel_jobs_link_only_exact_tool_receipts(rig: Any) -> None:
    receipt(rig, "tool:first", "tool", "ctx-first", "job-first")
    receipt(rig, "tool:second", "tool", "ctx-second", "job-second")
    receipt(rig, "job:first", "job", "ctx-first", "job-first")
    receipt(rig, "job:second", "job", "ctx-second", "job-second")
    edges = snapshot(rig)["edges"]
    assert {"from": "tool:first", "to": "job:first", "kind": "contains"} in edges
    assert {"from": "tool:second", "to": "job:second", "kind": "contains"} in edges
    assert {"from": "tool:first", "to": "job:second", "kind": "contains"} not in edges


def test_same_job_name_across_context_or_run_or_thread_does_not_link(rig: Any) -> None:
    receipt(rig, "tool:original", "tool", "ctx-one", "same-id")
    receipt(rig, "job:other-context", "job", "ctx-two", "same-id")
    receipt(rig, "job:other-run", "job", "ctx-one", "same-id", run="other-run")
    receipt(
        rig, "job:other-thread", "job", "ctx-one", "same-id", thread="child-thread", agent="child"
    )
    assert not [edge for edge in snapshot(rig)["edges"] if edge["from"] == "tool:original"]


def test_ambiguous_tool_receipts_leave_job_unlinked(rig: Any) -> None:
    receipt(rig, "tool:one", "tool", "ctx", "same-id")
    receipt(rig, "tool:two", "tool", "ctx", "same-id")
    receipt(rig, "job:one", "job", "ctx", "same-id")
    assert not [edge for edge in snapshot(rig)["edges"] if edge["to"] == "job:one"]


def test_ask_agent_canonical_invocation_counts_once_and_retains_task_link(rig: Any) -> None:
    service = CollaborationService(rig.manager)
    invocation = service.accept(call(rig, identity="delegated"))
    run = invocation["root_run_id"]
    activity = ActivityService(rig.manager)
    activity.plan(
        rig.owner,
        "parent",
        "root",
        run,
        WorkPlan.model_validate(
            {"plan_id": "plan", "revision": 0, "tasks": [{"task_id": "A", "title": "Review"}]}
        ),
    )
    RunEventRepo(rig.repos.db).save(
        event_id="tool:ask",
        owner=rig.owner,
        agent_id="parent",
        thread_id="root",
        run_id=run,
        context_id=None,
        kind="dispatch",
        status="running",
        payload={
            "name": "ask_agent",
            "invocation_id": "delegated",
            "task_id": "A",
            "attempt_id": "attempt",
        },
    )
    result = snapshot(rig)
    assert result["counts"]["subagents"] == 1
    assert not any(n["id"] == "tool:ask" for n in result["nodes"])
    node = next(n for n in result["nodes"] if n["id"] == "delegated")
    assert node["type"] == "delegation" and node["status"] == "accepted"
    assert node["task_id"] == "A" and node["attempt_id"] == "attempt"
    assert result["counts"]["parallel"] == 0
    assert any(e["kind"] == "contains" and e["to"] == "delegated" for e in result["edges"])


def test_native_dispatch_stays_independent_and_cross_run_receipt_is_not_merged(rig: Any) -> None:
    invocation = CollaborationService(rig.manager).accept(call(rig, identity="delegated"))
    events = RunEventRepo(rig.repos.db)
    for identity, payload, run in (
        ("dispatch:native", {"name": "task", "subagent_type": "child"}, invocation["root_run_id"]),
        ("dispatch:foreign-run", {"name": "ask_agent", "invocation_id": "delegated"}, "other-root"),
    ):
        events.save(
            event_id=identity,
            owner=rig.owner,
            agent_id="parent",
            thread_id="root",
            run_id=run,
            context_id=None,
            kind="dispatch",
            status="running",
            payload=payload,
        )
    result = snapshot(rig)
    assert result["counts"]["subagents"] == 3
    assert {"delegated", "dispatch:native", "dispatch:foreign-run"}.issubset(
        {n["id"] for n in result["nodes"]}
    )


def test_cross_thread_invocation_reference_is_not_merged(rig: Any) -> None:
    invocation = CollaborationService(rig.manager).accept(
        call(
            rig,
            identity="foreign-inv",
            from_agent_id="child",
            source_thread_id="child-thread",
            source_session_key="child-thread",
        )
    )
    RunEventRepo(rig.repos.db).save(
        event_id="dispatch:foreign",
        owner=rig.owner,
        agent_id="parent",
        thread_id="root",
        run_id=invocation["root_run_id"],
        context_id=None,
        kind="dispatch",
        status="running",
        payload={"name": "ask_agent", "invocation_id": "foreign-inv"},
    )
    result = snapshot(rig)
    assert result["counts"]["subagents"] == 1
    assert [n for n in result["nodes"] if n["type"] == "delegation"] == []


def test_status_tools_never_claim_job_production(rig: Any) -> None:
    events = RunEventRepo(rig.repos.db)
    for identity, name in (
        ("status", "job_status"),
        ("logs", "job_logs"),
        ("cancel", "job_cancel"),
    ):
        events.save(
            event_id=f"tool:{identity}",
            owner=rig.owner,
            agent_id="parent",
            thread_id="root",
            run_id="root-run",
            context_id="ctx",
            kind="tool",
            status="completed",
            payload={"name": name, "context_id": "ctx", "job_id": "job"},
        )
    receipt(rig, "job:real", "job", "ctx", "job")
    assert not [edge for edge in snapshot(rig)["edges"] if edge["to"] == "job:real"]


def test_installed_harness_job_start_sink_produces_exact_join(rig: Any) -> None:
    import json
    from uuid import uuid4

    from langchain_core.messages import ToolMessage
    from langgraph.config import var_child_runnable_config
    from octop_harness.observability.run_events import RunEventCallback

    from octop.infra.execution.events import RunInspectionService

    callback = RunEventCallback(
        lambda event: RunInspectionService(rig.repos).tool_receipt("parent", event)
    )
    token = var_child_runnable_config.set(
        {
            "configurable": {
                "user": rig.owner,
                "thread_id": "root",
                "octop_task_run_id": "root-run",
                "octop_execution_context": {"context_id": "ctx"},
            }
        }
    )
    identities = []
    try:
        for job in ("first", "second"):
            identity = uuid4()
            identities.append((f"tool:{identity}", job))
            callback.on_tool_start({"name": "job_start"}, "{}", run_id=identity)
            callback.on_tool_end(
                ToolMessage(
                    json.dumps({"context_id": "ctx", "job_id": job, "status": "running"}),
                    tool_call_id=job,
                ),
                run_id=identity,
            )
            receipt(rig, f"job:{job}", "job", "ctx", job)
    finally:
        var_child_runnable_config.reset(token)
    edges = snapshot(rig)["edges"]
    for tool, job in identities:
        assert {"from": tool, "to": f"job:{job}", "kind": "contains"} in edges


def test_accepted_native_dispatch_is_active_but_not_parallel_running(rig: Any) -> None:
    activity = ActivityService(rig.manager)
    activity.plan(
        rig.owner,
        "parent",
        "root",
        "root-run",
        WorkPlan.model_validate(
            {"plan_id": "waiting", "revision": 0, "tasks": [{"task_id": "A", "title": "Waiting"}]}
        ),
    )
    RunEventRepo(rig.repos.db).save(
        event_id="tool:waiting",
        owner=rig.owner,
        agent_id="parent",
        thread_id="root",
        run_id="root-run",
        context_id=None,
        kind="dispatch",
        status="accepted",
        payload={"name": "task", "task_id": "A"},
    )
    result = snapshot(rig)
    assert result["counts"]["subagents"] == 1
    assert result["counts"]["parallel"] == 0
    assert (
        next(node for node in result["nodes"] if node["id"] == "tool:waiting")["status"]
        == "waiting"
    )
