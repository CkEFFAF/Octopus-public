"""Exercise durable Graph behavior through real storage and boundary fakes."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from octop.infra.cron.delivery import WorkflowAdmissionDeferred
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.devices.service import DeviceService
from octop.infra.errors import OctopError
from octop.infra.execution.service import ExecutionService
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.workflow_graphs.middleware import project_messages
from octop.infra.workflow_graphs.models import GraphDefinition
from octop.infra.workflow_graphs.service import SaveGraph, StartRun, WorkflowGraphService
from octop.infra.workflow_graphs.state import ContextRecipe


@pytest.fixture
async def rig(tmp_path):
    db = SqlitePool(tmp_path / "graphs.sqlite")
    run_migrations(db)
    repos = RepoBundle.from_pool(db)
    owner = repos.user_repo.create(username="owner", password_hash="unused", role="admin")
    other = repos.user_repo.create(username="other", password_hash="unused", role="user")
    repos.agent_repo.create(agent_id="expert", user_id=owner, name="Expert")
    repos.agent_repo.create(agent_id="other", user_id=other, name="Other")
    repos.secret_repo.get_or_create("jwt", lambda: b"test-only-graph-key")
    gateway = SimpleNamespace(
        thread_registry=ThreadRegistry(
            session_repo=repos.session_repo, thread_repo=repos.thread_repo
        )
    )
    devices = DeviceService(repos, local_state_dir=tmp_path / "execution")
    delivery = SimpleNamespace(deliver=AsyncMock())
    service = WorkflowGraphService(
        repos=repos,
        registry=SimpleNamespace(),
        gateway=gateway,
        delivery=delivery,
        execution=ExecutionService(devices),
        timezone="Asia/Shanghai",
    )

    async def deliver(command):
        if not command.on_admission():
            raise WorkflowAdmissionDeferred()
        return '{"continue":false,"value":7}'

    delivery.deliver.side_effect = deliver
    yield SimpleNamespace(
        service=service, owner=owner, other=other, repos=repos, delivery=delivery, root=tmp_path
    )
    await service.shutdown()
    await devices.shutdown()
    db.close()


def definition(nodes, edges, **kwargs):
    return GraphDefinition.model_validate(
        {
            "name": "Research",
            "agent_id": "expert",
            "nodes": [
                {"id": "start", "kind": "entry", "label": "Start"},
                *nodes,
                {"id": "end", "kind": "end", "label": "End"},
            ],
            "edges": [
                {"id": f"e{i}", "source": source, "target": target, "port": port}
                for i, (source, target, port) in enumerate(edges)
            ],
            **kwargs,
        }
    )


def publish(rig, graph, key="research"):
    view = rig.service.save(rig.owner, SaveGraph(graph_id=key, revision=0, definition=graph))
    rig.service.publish(rig.owner, key, view.revision)


async def drain(service, rounds=12):
    for _ in range(rounds):
        await service.tick()
        if service.runner.tasks:
            await asyncio.wait_for(asyncio.gather(*list(service.runner.tasks.values())), 3)
        await asyncio.sleep(0)


async def test_agent_routes_new_context_restores_parent_and_pins_version(rig):
    graph = definition(
        [
            {
                "id": "analyze",
                "kind": "agent",
                "label": "Analyze",
                "prompt": "Analyze",
                "output_mode": "json",
                "context": {
                    "before": {"session": "new", "history": "empty", "inject": "prior"},
                    "after": {"session": "restore", "context": "keep"},
                },
            }
        ],
        [("start", "analyze", "next"), ("analyze", "end", "next")],
    )
    publish(rig, graph)
    run = await rig.service.start(rig.owner, "research", StartRun(request_id="one"))
    view = rig.service.save(
        rig.owner,
        SaveGraph(
            graph_id="research",
            revision=1,
            definition=graph.model_copy(update={"name": "New draft"}),
        ),
    )
    assert view.revision == 2
    await drain(rig.service)
    assert rig.service.run(rig.owner, run["id"])["status"] == "succeeded"
    rows = rig.service.store.activations(rig.owner, run["id"])
    before = json.loads(rows[1]["before_json"])
    after = json.loads(rows[1]["after_json"])
    origin = json.loads(rows[1]["token_json"])["conversation"]
    assert before["thread_id"] != origin["thread_id"]
    assert after["conversation"]["thread_id"] == origin["thread_id"]
    assert after["conversation"]["recipe"]["history"] == "empty"
    assert after["outputs"]["analyze"]["result"]["value"] == 7
    assert rig.service.run(rig.owner, run["id"])["version"] == 1
    assert (await rig.service.start(rig.owner, "research", StartRun(request_id="one")))[
        "id"
    ] == run["id"]


async def test_early_signal_survives_runner_recreation_and_is_not_delivered_as_cron(rig):
    graph = definition(
        [
            {"id": "event", "kind": "event", "label": "Ready", "event_type": "eval.ready"},
            {"id": "wait", "kind": "wait_event", "label": "Wait", "event_node": "event"},
        ],
        [("start", "event", "next"), ("event", "wait", "next"), ("wait", "end", "next")],
    )
    publish(rig, graph)
    run = await rig.service.start(rig.owner, "research", StartRun(request_id="early"))
    await drain(rig.service, 2)
    rows = rig.service.store.activations(rig.owner, run["id"])
    hook_id = json.loads(rows[1]["output_json"])["hook_id"]
    hook = rig.service.hooks.events.wakeup_hook(hook_id)
    token = rig.service.hooks._token(hook)
    rig.service.hooks.fire(hook_id, token, "eval.ready", {"score": 0.9})
    cron = SimpleNamespace(get=lambda _: None, create=AsyncMock())
    await rig.service.hooks.tick(cron)
    cron.create.assert_not_called()
    from octop.infra.workflow_graphs.runner import WorkflowRunner

    rig.service.runner = WorkflowRunner(rig.service)
    await drain(rig.service)
    assert rig.service.run(rig.owner, run["id"])["status"] == "succeeded"
    wait = rig.service.store.activations(rig.owner, run["id"])[2]
    assert json.loads(wait["output_json"])["result"] == {"score": 0.9}
    assert token not in json.dumps(rig.service.inspect(rig.owner, wait["id"]))
    assert rig.service.hooks.fire(hook_id, token, "eval.ready", {"score": 0.9})["duplicate"]


async def test_fork_join_merges_once_and_respects_branch_local_state(rig):
    graph = definition(
        [
            {"id": "fork", "kind": "fork", "label": "Parallel", "join_id": "join"},
            {"id": "left", "kind": "condition", "label": "Left", "assign": {"score": {"value": 1}}},
            {
                "id": "right",
                "kind": "condition",
                "label": "Right",
                "assign": {"score": {"value": 2}},
            },
            {
                "id": "join",
                "kind": "join",
                "label": "Join",
                "fork_id": "fork",
                "merge": {
                    "e1": {"left": {"path": "$.vars.score"}},
                    "e2": {"right": {"path": "$.vars.score"}},
                },
            },
        ],
        [
            ("start", "fork", "next"),
            ("fork", "left", "next"),
            ("fork", "right", "next"),
            ("left", "join", "true"),
            ("left", "join", "false"),
            ("right", "join", "true"),
            ("right", "join", "false"),
            ("join", "end", "next"),
        ],
    )
    publish(rig, graph)
    run = await rig.service.start(rig.owner, "research", StartRun(request_id="parallel"))
    await drain(rig.service)
    assert rig.service.run(rig.owner, run["id"])["status"] == "succeeded"
    rows = rig.service.store.activations(rig.owner, run["id"])
    ends = [row for row in rows if row["kind"] == "end"]
    assert len(ends) == 1
    assert json.loads(ends[0]["token_json"])["variables"] == {"left": 1, "right": 2}


async def test_bounded_loop_pauses_without_replaying_on_subsequent_ticks(rig):
    graph = definition(
        [{"id": "again", "kind": "condition", "label": "Repeat"}],
        [("start", "again", "next"), ("again", "again", "true"), ("again", "end", "false")],
        limits={"max_steps": 4, "max_seconds": 3600, "max_parallel": 4},
    )
    publish(rig, graph)
    run = await rig.service.start(rig.owner, "research", StartRun(request_id="loop"))
    await drain(rig.service)
    state = rig.service.run(rig.owner, run["id"])
    assert state["status"] == "paused" and state["steps"] == 4
    count = len(rig.service.store.activations(rig.owner, run["id"]))
    await drain(rig.service)
    assert len(rig.service.store.activations(rig.owner, run["id"])) == count


async def test_event_start_capability_is_scoped_revocable_and_deduplicated(rig):
    graph = definition([], [("start", "end", "next")], event_start=True)
    publish(rig, graph)
    credential = rig.service.capability(rig.owner, "research")
    run = await rig.service.fire("research", credential["token"], "event1", {"x": 1})
    assert (await rig.service.fire("research", credential["token"], "event1", {"x": 1}))[
        "id"
    ] == run["id"]
    with pytest.raises(ValueError):
        await rig.service.fire("research", credential["token"], "event1", {"x": 2})
    with pytest.raises(OctopError):
        rig.service.inspect(rig.other, rig.service.store.activations(rig.owner, run["id"])[0]["id"])
    rig.service.capability(rig.owner, "research", revoke=True)
    with pytest.raises(OctopError):
        await rig.service.fire("research", credential["token"], "event2", {})


def test_context_projection_preserves_system_and_tool_pairs_without_mutation():
    messages = [
        SystemMessage("rules"),
        HumanMessage("old"),
        AIMessage(content="", tool_calls=[{"id": "call", "name": "read", "args": {}}]),
        HumanMessage("task"),
        ToolMessage("receipt", tool_call_id="call"),
    ]
    projected = project_messages(messages, ContextRecipe(history="empty", inject="facts"))
    assert projected[0] is messages[0]
    assert messages[2] in projected and messages[4] in projected
    assert projected[-1].content.endswith("facts")
    assert len(messages) == 5


async def local_source(rig):
    thread = await rig.service.thread(rig.owner, "expert", "source")
    return rig.service.execution.resolve(
        rig.owner,
        target_kind="local",
        agent_id="expert",
        thread_id=thread,
        working_dir=str(rig.root),
    )


async def test_script_uses_frozen_cwd_environment_and_real_terminal_receipt(rig):
    source = await local_source(rig)
    graph = definition(
        [
            {
                "id": "script",
                "kind": "script",
                "label": "Read iteration input",
                "argv": [
                    sys.executable,
                    "-c",
                    "import os,json; print(json.dumps({'cwd':os.getcwd(),'input':json.loads(os.environ['OCTOPUS_WORKFLOW_INPUT'])}))",
                ],
                "inputs": {"score": {"value": 7}},
                "output_mode": "json",
            }
        ],
        [("start", "script", "next"), ("script", "end", "next")],
        execution_context_id=source.context_id,
    )
    publish(rig, graph)
    run = await rig.service.start(rig.owner, "research", StartRun(request_id="script"))
    await drain(rig.service, 2)
    rows = rig.service.store.activations(rig.owner, run["id"])
    job = rows[1]
    assert job["status"] == "waiting_job" and job["capacity_held"] == 1
    evidence = json.loads(job["evidence_json"])
    for _ in range(300):
        receipt = await rig.service.execution.call(
            rig.owner,
            evidence["context_id"],
            "jobs.status",
            {"job_id": evidence["job_id"]},
            actor_agent_id="expert",
        )
        if receipt["result"]["status"] in {"completed", "failed"}:
            break
        await asyncio.sleep(0.1)
    assert receipt["result"]["status"] == "completed"
    assert "env" not in receipt["result"]
    assert await rig.service.runner.observe(job)
    output = rig.service.inspect(rig.owner, job["id"])["output"]["result"]
    assert output["cwd"] == str(rig.root)
    assert output["input"] == {"score": 7}
    await drain(rig.service, 2)
    assert rig.service.run(rig.owner, run["id"])["status"] == "succeeded"


async def test_failed_script_preflight_releases_capacity_without_unknown_outcome(rig):
    source = await local_source(rig)
    graph = definition(
        [
            {
                "id": "script",
                "kind": "script",
                "label": "Evaluate",
                "argv": ["unused"],
                "callback_node": "event",
            },
            {"id": "event", "kind": "event", "label": "Register later"},
        ],
        [("start", "script", "next"), ("script", "event", "next"), ("event", "end", "next")],
        execution_context_id=source.context_id,
    )
    publish(rig, graph)
    run = await rig.service.start(rig.owner, "research", StartRun(request_id="preflight"))
    await drain(rig.service, 3)
    script = rig.service.store.activations(rig.owner, run["id"])[1]
    assert script["status"] == "failed" and script["capacity_held"] == 0
    assert rig.service.run(rig.owner, run["id"])["status"] == "failed"


async def test_reconciliation_looks_up_original_job_without_starting_a_command(rig, monkeypatch):
    source = await local_source(rig)
    graph = definition(
        [{"id": "script", "kind": "script", "label": "Evaluate", "argv": ["unused"]}],
        [("start", "script", "next"), ("script", "end", "next")],
        execution_context_id=source.context_id,
    )
    publish(rig, graph)
    boundary = rig.service.execution.local_backend(rig.owner)
    call = AsyncMock(side_effect=TimeoutError())
    monkeypatch.setattr(boundary, "call", call)
    run = await rig.service.start(rig.owner, "research", StartRun(request_id="lost"))
    await drain(rig.service, 2)
    row = rig.service.store.activations(rig.owner, run["id"])[1]
    assert row["status"] == "unknown" and row["capacity_held"] == 1
    call.reset_mock()
    call.side_effect = None
    import hashlib

    job_id = hashlib.sha256(("graph-" + row["id"]).encode()).hexdigest()[:32]
    call.return_value = {"job_id": job_id, "status": "running"}
    await rig.service.runner.reconcile(rig.owner, row["id"])
    assert [item.args[2] for item in call.await_args_list] == ["jobs.status"]


async def test_one_signal_cannot_complete_two_loop_activations(rig):
    graph = definition(
        [
            {"id": "event", "kind": "event", "label": "Ready"},
            {"id": "wait", "kind": "wait_event", "label": "Wait", "event_node": "event"},
            {"id": "again", "kind": "condition", "label": "Again"},
        ],
        [
            ("start", "event", "next"),
            ("event", "wait", "next"),
            ("wait", "again", "next"),
            ("again", "wait", "true"),
            ("again", "end", "false"),
        ],
    )
    publish(rig, graph)
    run = await rig.service.start(rig.owner, "research", StartRun(request_id="one-signal"))
    await drain(rig.service, 3)
    rows = rig.service.store.activations(rig.owner, run["id"])
    hook = rig.service.hooks.events.wakeup_hook(json.loads(rows[1]["output_json"])["hook_id"])
    rig.service.hooks.fire(hook["event_id"], rig.service.hooks._token(hook), "event.ready", {})
    await rig.service.runner.observe(rows[2])
    await drain(rig.service, 5)
    waits = [
        r for r in rig.service.store.activations(rig.owner, run["id"]) if r["node_id"] == "wait"
    ]
    assert [r["status"] for r in waits] == ["completed", "failed"]


async def test_wait_observation_rotates_past_a_full_batch(rig):
    branch_nodes = []
    links = [("start", "fork", "next")]
    for i in range(5):
        branch_nodes.extend(
            [
                {"id": f"event{i}", "kind": "event", "label": "Register"},
                {
                    "id": f"wait{i}",
                    "kind": "wait_event",
                    "label": "Wait",
                    "event_node": f"event{i}",
                },
            ]
        )
        links.extend(
            [
                ("fork", f"event{i}", "next"),
                (f"event{i}", f"wait{i}", "next"),
                (f"wait{i}", "join", "next"),
            ]
        )
    links.append(("join", "end", "next"))
    graph = definition(
        [
            {"id": "fork", "kind": "fork", "label": "Parallel", "join_id": "join"},
            *branch_nodes,
            {"id": "join", "kind": "join", "label": "Join", "fork_id": "fork"},
        ],
        links,
    )
    publish(rig, graph)
    for i in range(32):
        await rig.service.start(rig.owner, "research", StartRun(request_id=f"wait{i}"))
    await drain(rig.service, 6)
    with rig.service.store.db.transaction() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM workflow_activations WHERE status='waiting_event'"
            ).fetchone()[0]
            == 160
        )
        conn.execute(
            "UPDATE workflow_activations SET next_at=NULL,updated_at=created_at WHERE status='waiting_event'"
        )
        target = dict(
            conn.execute(
                "SELECT * FROM workflow_activations WHERE status='waiting_event' ORDER BY updated_at DESC,id DESC LIMIT 1"
            ).fetchone()
        )
    hook_id = json.loads(target["evidence_json"])["hook_id"]
    hook = rig.service.hooks.events.wakeup_hook(hook_id)
    rig.service.hooks.fire(
        hook_id, rig.service.hooks._token(hook), "event.ready", {"arrived": True}
    )
    await drain(rig.service, 2)
    assert rig.service.store.activation(rig.owner, target["id"])["status"] == "completed"
    with rig.service.store.db.connect() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM workflow_activations WHERE status='waiting_event'"
            ).fetchone()[0]
            == 159
        )


@pytest.mark.parametrize(
    "config",
    [
        {"work_mode": "ask"},
        {"work_mode": "plan"},
        {"octop_shared_text_scope": {"owner": "foreign"}},
    ],
)
async def test_graph_tools_cannot_bypass_read_only_modes_or_shared_scope(rig, config):
    from langgraph.config import var_child_runnable_config

    from octop.infra.workflow_graphs.tools import build_workflow_tools

    token = var_child_runnable_config.set({"configurable": {"user": rig.owner, **config}})
    try:
        tool = next(
            t for t in build_workflow_tools(rig.service, "expert") if t.name == "workflow_graph"
        )
        result = json.loads(await tool.ainvoke({"operation": "capability", "graph_id": "missing"}))
        assert "observation only" in result["error"] or "shared text" in result["error"]
    finally:
        var_child_runnable_config.reset(token)


async def test_http_normalizes_import_and_inspects_unfinished_non_agent_nodes(rig):
    import httpx
    from fastapi import FastAPI

    from octop.api.deps import current_user
    from octop.api.routers import workflow_graphs as routes

    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    app.dependency_overrides[routes.service] = lambda: rig.service
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=rig.owner)
    minimal = {
        "name": "Minimal",
        "agent_id": "expert",
        "nodes": [
            {"id": "start", "kind": "entry", "label": "Start"},
            {"id": "end", "kind": "end", "label": "End"},
        ],
        "edges": [{"id": "next", "source": "start", "target": "end"}],
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        result = await client.post("/api/workflow-graphs/normalize", json=minimal)
        assert result.status_code == 200
        normalized = result.json()["definition"]
        assert normalized["nodes"][0]["position"] == {"x": 0, "y": 0}
        assert normalized["edges"][0]["port"] == "next"
        bad = {**minimal, "schedule": {"cron": "0 9 * * *", "timezone": "No/SuchTimezone"}}
        assert (await client.post("/api/workflow-graphs/normalize", json=bad)).status_code == 422
        assert (
            await client.put(
                "/api/workflow-graphs",
                json={"graph_id": "http", "revision": 0, "definition": normalized},
            )
        ).status_code == 200
        assert (
            await client.post("/api/workflow-graphs/http/publish", json={"revision": 1})
        ).status_code == 200
        run = (
            await client.post("/api/workflow-graphs/http/start", json={"request_id": "once"})
        ).json()
        page = (await client.get(f"/api/workflow-graphs/runs/{run['id']}/timeline")).json()
        activation_id = page["items"][0]["id"]
        assert (
            await client.get(f"/api/workflow-graphs/activations/{activation_id}")
        ).status_code == 200
        await drain(rig.service, 2)
        detail = await client.get(f"/api/workflow-graphs/activations/{activation_id}")
        assert detail.status_code == 200 and detail.json()["after"]["conversation"]["thread_id"]
        assert "worker_id" not in detail.json()


async def test_confirmed_dead_model_workers_release_reservations_without_replaying(rig):
    import socket

    graph = definition(
        [{"id": "agent", "kind": "agent", "label": "Analyze", "prompt": "Analyze"}],
        [("start", "agent", "next"), ("agent", "end", "next")],
    )
    publish(rig, graph)
    runs = [
        await rig.service.start(rig.owner, "research", StartRun(request_id=str(i)))
        for i in range(4)
    ]
    await drain(rig.service, 1)
    dead_worker = json.dumps(
        {"host": socket.gethostname(), "process": {"pid": 99999999, "created_at": 1}}
    )
    for run in runs:
        row = next(
            r for r in rig.service.store.activations(rig.owner, run["id"]) if r["kind"] == "agent"
        )
        assert rig.service.store.claim(rig.owner, row["id"], dead_worker, time.time())
        with rig.repos.db.transaction() as conn:
            conn.execute("UPDATE workflow_activations SET lease_until=0 WHERE id=?", (row["id"],))
    from octop.infra.workflow_graphs.runner import WorkflowRunner

    rig.service.runner = WorkflowRunner(rig.service)
    await drain(rig.service, 1)
    rig.delivery.deliver.assert_not_called()
    for run in runs:
        row = next(
            r for r in rig.service.store.activations(rig.owner, run["id"]) if r["kind"] == "agent"
        )
        assert row["status"] == "unknown" and row["capacity_held"] == 0
    rig.service.retry(rig.owner, row["id"])
    await drain(rig.service, 3)
    assert rig.service.run(rig.owner, run["id"])["status"] == "succeeded"


async def test_schedule_restart_skips_missed_occurrence_and_live_tick_deduplicates(rig):
    graph = definition(
        [], [("start", "end", "next")], schedule={"cron": "0 9 * * *", "timezone": "Asia/Shanghai"}
    )
    publish(rig, graph)
    yesterday = time.time() - 86400
    with rig.repos.db.transaction() as conn:
        conn.execute("UPDATE workflow_graphs SET next_due_at=?", (yesterday,))
    rig.service.recover()
    assert rig.service.runs(rig.owner, "research", 10, 0).total == 0
    assert rig.service.store.get(rig.owner, "research")["next_due_at"] > time.time()
    with rig.repos.db.transaction() as conn:
        conn.execute("UPDATE workflow_graphs SET next_due_at=?", (time.time() - 1,))
    await drain(rig.service, 3)
    assert rig.service.runs(rig.owner, "research", 10, 0).total == 1


async def test_canonical_event_retries_accept_nested_object_key_reordering(rig):
    publish(rig, definition([], [("start", "end", "next")], event_start=True))
    token = rig.service.capability(rig.owner, "research")["token"]
    first = await rig.service.fire("research", token, "ordered", {"a": 1, "b": {"x": 2, "y": 3}})
    second = await rig.service.fire("research", token, "ordered", {"b": {"y": 3, "x": 2}, "a": 1})
    assert first["id"] == second["id"]


async def test_join_error_route_consumes_all_arrivals_and_rejects_single_arrival_retry(rig):
    graph = definition(
        [
            {"id": "fork", "kind": "fork", "label": "Fork", "join_id": "join"},
            {"id": "a", "kind": "agent", "label": "A", "prompt": "A"},
            {"id": "b", "kind": "agent", "label": "B", "prompt": "B"},
            {
                "id": "join",
                "kind": "join",
                "label": "Join",
                "fork_id": "fork",
                "merge": {"e1": {"missing": {"path": "$.vars.absent"}}},
            },
        ],
        [
            ("start", "fork", "next"),
            ("fork", "a", "next"),
            ("fork", "b", "next"),
            ("a", "join", "next"),
            ("b", "join", "next"),
            ("join", "end", "next"),
            ("join", "end", "error"),
        ],
    )
    publish(rig, graph)
    run = await rig.service.start(rig.owner, "research", StartRun(request_id="bad-merge"))
    await drain(rig.service)
    rows = rig.service.store.activations(rig.owner, run["id"])
    assert rig.service.run(rig.owner, run["id"])["status"] == "succeeded"
    assert len([r for r in rows if r["kind"] == "end"]) == 1
    joins = [r for r in rows if r["kind"] == "join"]
    assert len(joins) == 2 and all(r["status"] == "failed" for r in joins)
    with pytest.raises(ValueError, match="cannot be retried alone"):
        rig.service.retry(rig.owner, joins[0]["id"])


async def test_signal_hooks_do_not_block_normal_wakeup_admission(rig):
    thread = await rig.service.thread(rig.owner, "expert", "signals")
    for i in range(130):
        hook = rig.service.hooks.register(
            rig.owner,
            "expert",
            thread,
            title="Signal",
            event_type="ready",
            purpose="Signal only",
            idempotency_key=str(i),
            delivery_mode="signal",
        )
        rig.service.hooks.fire(hook["hook_id"], hook["token"], "ready", {})
    wake = rig.service.hooks.register(
        rig.owner,
        "expert",
        thread,
        title="Notify",
        event_type="ready",
        purpose="Wake expert",
        idempotency_key="normal",
    )
    rig.service.hooks.fire(wake["hook_id"], wake["token"], "ready", {})
    assert [row["event_id"] for row in rig.repos.run_event_repo.pending_wakeup_hooks(limit=1)] == [
        wake["hook_id"]
    ]


async def test_busy_conversation_uses_the_canonical_lock_without_queuing(rig):
    from octop_gateway.manager import ChannelManager

    from octop.infra.gateway.gateway import Gateway

    manager = ChannelManager(channels={"test": SimpleNamespace()})
    gateway = Gateway.__new__(Gateway)
    gateway._channel_manager = manager
    gateway._channel_id_for_session = lambda _: "test"
    session = SimpleNamespace(channel_type="dashboard", thread_id="origin", session_key="origin")
    entered, release = asyncio.Event(), asyncio.Event()

    async def incoming():
        entered.set()
        await release.wait()

    task = asyncio.create_task(manager.run_in_session("test", "thread:origin", incoming))
    await entered.wait()
    operation = AsyncMock()
    assert not await gateway.try_run_locked_on_session(session, operation)
    operation.assert_not_called()
    release.set()
    await task
    assert await gateway.try_run_locked_on_session(session, operation)
    operation.assert_awaited_once()


async def test_frozen_execution_source_selects_mcp_pack_even_when_expert_binding_changes(rig):
    from unittest.mock import MagicMock

    from octop.infra.cron.delivery import CronDeliveryCommand, CronDeliveryService

    source = await local_source(rig)
    manager = MagicMock()
    manager.get_row.return_value = rig.repos.agent_repo.get("expert")
    manager.default_mcp_servers.return_value = []
    manager.device_mcp_pack_for_turn.return_value = ([], [])
    manager.merge_turn_mcp_servers.return_value = []
    manager.default_knowledge_base_ids.return_value = []
    command = CronDeliveryCommand(
        cron_id="graph",
        cron_name="Graph",
        agent_id="expert",
        user_id=rig.owner,
        session_key="source",
        prompt="Analyze",
        fresh_thread=False,
        task_type="agent",
        model=None,
        mcp_servers=(),
        workflow_context={"recipe": {"history": "full"}},
        workflow_execution_context_id=source.context_id,
    )
    session = SimpleNamespace(
        user_id=rig.owner,
        agent_id="expert",
        thread_id=source.thread_id,
        channel_type="dashboard",
        session_key="source",
    )
    delivery = CronDeliveryService(gateway=MagicMock(), agent_manager=manager, repos=rig.repos)
    await delivery._build_agent_request(command, session)
    manager.device_mcp_pack_for_turn.assert_called_once_with(
        rig.owner, agent_id="expert", thread_id=source.thread_id, resolved_device_id=""
    )


async def test_read_only_execution_source_is_rejected_without_reserving_a_job(rig):
    source = await local_source(rig)
    readonly = rig.service.execution.resolve(
        rig.owner,
        target_kind="local",
        agent_id="expert",
        thread_id=source.thread_id,
        working_dir=str(rig.root),
        work_mode="ask",
    )
    graph = definition(
        [{"id": "script", "kind": "script", "label": "Evaluate", "argv": ["unused"]}],
        [("start", "script", "next"), ("script", "end", "next")],
        execution_context_id=readonly.context_id,
    )
    publish(rig, graph)
    run = await rig.service.start(rig.owner, "research", StartRun(request_id="ask-source"))
    await drain(rig.service, 3)
    script = rig.service.store.activations(rig.owner, run["id"])[1]
    assert script["status"] == "failed" and script["capacity_held"] == 0


async def test_expired_script_dispatch_fence_prevents_a_receiver_call(rig, monkeypatch):
    source = await local_source(rig)
    graph = definition(
        [{"id": "script", "kind": "script", "label": "Evaluate", "argv": ["unused"]}],
        [("start", "script", "next"), ("script", "end", "next")],
        execution_context_id=source.context_id,
    )
    publish(rig, graph)
    boundary = AsyncMock()
    monkeypatch.setattr(rig.service.execution.local_backend(rig.owner), "call", boundary)
    prepare = rig.service.execution._prepare

    def expire(*args, **kwargs):
        result = prepare(*args, **kwargs)
        rig.service.store.expire_leases(time.time() + 121)
        return result

    monkeypatch.setattr(rig.service.execution, "_prepare", expire)
    run = await rig.service.start(rig.owner, "research", StartRun(request_id="fence"))
    await drain(rig.service, 3)
    boundary.assert_not_called()
    script = rig.service.store.activations(rig.owner, run["id"])[1]
    assert script["status"] == "unknown" and script["capacity_held"] == 0


async def test_cancel_jobs_reports_in_flight_until_a_terminal_receipt_arrives(rig, monkeypatch):
    source = await local_source(rig)
    graph = definition(
        [{"id": "script", "kind": "script", "label": "Evaluate", "argv": ["unused"]}],
        [("start", "script", "next"), ("script", "end", "next")],
        execution_context_id=source.context_id,
    )
    publish(rig, graph)
    boundary = AsyncMock(return_value={"job_id": "accepted", "status": "running"})
    monkeypatch.setattr(rig.service.execution.local_backend(rig.owner), "call", boundary)
    run = await rig.service.start(rig.owner, "research", StartRun(request_id="cancel"))
    await drain(rig.service, 2)
    cancelled = await rig.service.runner.cancel_jobs(rig.owner, run["id"])
    assert cancelled["jobs"][0]["status"] == "running"
    assert cancelled["run"]["status"] == "cancelling"
    row = rig.service.store.activations(rig.owner, run["id"])[1]
    assert row["capacity_held"] == 1
    evidence = json.loads(row["evidence_json"])
    boundary.return_value = {"job_id": "accepted", "status": "cancelled"}
    await rig.service.execution.call(
        rig.owner,
        evidence["context_id"],
        "jobs.status",
        {"job_id": "accepted"},
        actor_agent_id="expert",
    )
    await rig.service.runner.observe(row)
    assert rig.service.run(rig.owner, run["id"])["status"] == "cancelled"


async def test_preflight_error_loops_obey_the_step_budget(rig):
    graph = definition(
        [
            {
                "id": "bad",
                "kind": "condition",
                "label": "Missing input",
                "inputs": {"missing": {"path": "$.vars.absent"}},
            }
        ],
        [
            ("start", "bad", "next"),
            ("bad", "end", "true"),
            ("bad", "end", "false"),
            ("bad", "bad", "error"),
        ],
        limits={"max_steps": 4, "max_seconds": 3600},
    )
    publish(rig, graph)
    run = await rig.service.start(rig.owner, "research", StartRun(request_id="error-loop"))
    await drain(rig.service)
    result = rig.service.run(rig.owner, run["id"])
    assert result["status"] == "paused" and result["steps"] == 4
    assert len(rig.service.store.activations(rig.owner, run["id"])) == 5
