"""Workflow completion uses actual receipts, frozen run scope and human decisions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.errors import OctopError
from octop.infra.execution.work_mode import WorkModeService, build_work_mode_tools


@pytest.fixture
def workflow(tmp_path: Path) -> Any:
    db = SqlitePool(tmp_path / "workflows.db")
    run_migrations(db)
    repos = RepoBundle.from_pool(db)
    owner = repos.user_repo.create(username="owner", password_hash="unused", role="admin")
    other = repos.user_repo.create(username="other", password_hash="unused", role="user")
    repos.agent_repo.create(agent_id="expert", user_id=owner, name="Expert")
    repos.thread_repo.insert(
        thread_id="thread",
        user_id=owner,
        agent_id="expert",
        channel_type="dashboard",
        session_key="work",
    )
    yield WorkModeService(repos), owner, other
    db.close()


def config(owner: int, mode: str) -> dict[str, Any]:
    return {"thread_id": "thread", "user": owner, "octop_task_run_id": "run", "work_mode": mode}


def receipt(
    service: WorkModeService,
    owner: int,
    identity: str,
    *,
    kind: str = "tool",
    status: str = "completed",
    run_id: str = "run",
    payload: dict[str, Any] | None = None,
) -> str:
    service.events.save(
        event_id=identity,
        owner=owner,
        agent_id="expert",
        thread_id="thread",
        run_id=run_id,
        context_id=None,
        kind=kind,
        status=status,
        payload=payload or {},
    )
    return identity


def advance(
    service: WorkModeService,
    owner: int,
    cfg: dict[str, Any],
    stage: str,
    evidence: list[str] | None = None,
    **values: Any,
) -> dict[str, Any]:
    event = service.begin(owner, "expert", cfg)
    return service.step(
        owner,
        "expert",
        cfg,
        version=event["payload"]["version"],
        stage=stage,
        status="completed",
        report="Observed result",
        evidence_ids=evidence or [],
        **values,
    )


def test_debug_stages_require_real_scope_and_post_fix_verification(workflow: Any) -> None:
    service, owner, other = workflow
    cfg = config(owner, "debug")
    event = service.begin(owner, "expert", cfg)
    with pytest.raises(OctopError, match="current workflow stage"):
        advance(service, owner, cfg, "fix")
    with pytest.raises(OctopError, match="actual observations"):
        advance(service, owner, cfg, "reproduce")
    failed = receipt(service, owner, "reproduction", status="failed")
    advance(service, owner, cfg, "reproduce", [failed])
    with pytest.raises(OctopError, match="workflow changed"):
        service.step(
            owner,
            "expert",
            cfg,
            version=0,
            stage="diagnose",
            status="completed",
            report="stale report",
            evidence_ids=[failed],
        )
    wrong = receipt(service, owner, "wrong-run", run_id="elsewhere")
    with pytest.raises(OctopError, match="this run"):
        advance(service, owner, cfg, "diagnose", [wrong])
    advance(service, owner, cfg, "diagnose", [failed])
    old_check = receipt(service, owner, "old-check")
    advance(service, owner, cfg, "fix")
    with pytest.raises(OctopError, match="after the fix"):
        advance(service, owner, cfg, "verify", [old_check])
    new_check = receipt(service, owner, "new-check")
    final = advance(service, owner, cfg, "verify", [new_check])
    assert final["status"] == "completed"
    restored = WorkModeService(service.repos)
    assert restored.begin(owner, "expert", cfg)["payload"]["version"] == 4
    with pytest.raises(OctopError, match="thread unavailable"):
        restored.begin(other, "expert", cfg)
    assert event["payload"]["version"] == 0


@pytest.mark.parametrize(("mode", "required"), [("team", 1), ("multitask", 2)])
def test_accepted_dispatch_is_not_finished_work(workflow: Any, mode: str, required: int) -> None:
    service, owner, _ = workflow
    cfg = config(owner, mode)
    advance(service, owner, cfg, "decompose")
    first = receipt(service, owner, "peer-one", kind="dispatch", status="accepted")
    with pytest.raises(OctopError, match="final receipt"):
        advance(service, owner, cfg, "dispatch", [first])
    receipt(service, owner, first, kind="dispatch")
    ids = [first]
    if required == 2:
        with pytest.raises(OctopError, match="completed dispatch"):
            advance(service, owner, cfg, "dispatch", ids)
        ids.append(receipt(service, owner, "peer-two", kind="dispatch"))
    advance(service, owner, cfg, "dispatch", ids)
    assert advance(service, owner, cfg, "integrate", ids)["status"] == "completed"


def test_research_requires_distinct_retrieved_sources(workflow: Any) -> None:
    service, owner, _ = workflow
    cfg = config(owner, "deep_research")
    one = receipt(
        service, owner, "source-one", payload={"source_urls": ["https://example.org/paper"]}
    )
    advance(service, owner, cfg, "collect", [one])
    with pytest.raises(OctopError, match="two URLs"):
        advance(service, owner, cfg, "compare", [one])
    two = receipt(
        service, owner, "source-two", payload={"source_urls": ["https://example.net/report"]}
    )
    advance(service, owner, cfg, "compare", [one, two])
    assert advance(service, owner, cfg, "synthesize", [one, two])["status"] == "completed"


def test_cowork_decision_is_a_human_artifact_and_cannot_be_answered_by_model(workflow: Any) -> None:
    service, owner, other = workflow
    cfg = config(owner, "cowork")
    advance(service, owner, cfg, "work")
    with pytest.raises(OctopError, match="only the user"):
        advance(service, owner, cfg, "handoff")
    assert service.begin(owner, "expert", cfg)["payload"]["version"] == 1
    event = service.step(
        owner,
        "expert",
        cfg,
        stage="handoff",
        version=1,
        status="needs_input",
        report="Please choose a route",
        evidence_ids=[],
        decision={"question": "Which route?", "options": ["A", "B"], "recommendation": 0},
    )
    with pytest.raises(OctopError, match="only the user"):
        advance(service, owner, cfg, "handoff")
    with pytest.raises(OctopError):
        service.decide(other, "expert", "thread", event["event_id"], version=2, choice=0)
    chosen = service.decide(owner, "expert", "thread", event["event_id"], version=2, choice=1)
    assert chosen["payload"]["stages"][-1]["decision"]["choice"] == 1
    assert chosen["status"] == "completed"
    with pytest.raises(OctopError, match="handoff changed"):
        service.decide(owner, "expert", "thread", event["event_id"], version=2, choice=0)


def test_plan_and_interaction_require_real_artifacts(workflow: Any) -> None:
    service, owner, _ = workflow
    cfg = config(owner, "plan")
    advance(service, owner, cfg, "explore")
    todos = receipt(service, owner, "todos", kind="plan", payload={"name": "write_todos"})
    with pytest.raises(OctopError, match="plan artifact"):
        advance(service, owner, cfg, "plan", [todos])
    plan = receipt(
        service, owner, "plan-file", kind="plan", payload={"file_path": "/.agent/plans/work.md"}
    )
    advance(service, owner, cfg, "plan", [plan])
    cfg = {**config(owner, "computer_use"), "octop_task_run_id": "desktop-run"}
    advance(service, owner, cfg, "observe")
    with pytest.raises(OctopError, match="interaction session"):
        advance(service, owner, cfg, "interact")
    frame = receipt(
        service,
        owner,
        "desktop",
        run_id="desktop-run",
        kind="interaction",
        payload={"action": "desktop.input", "session_id": "real-session"},
    )
    advance(service, owner, cfg, "interact", [frame])


@pytest.mark.asyncio
async def test_public_graph_enforces_debug_write_sequence(workflow: Any) -> None:
    from deepagents import create_deep_agent
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langchain_core.tools import tool

    from octop.infra.agents.middleware.work_mode import WorkModeMiddleware

    class Model(FakeMessagesListChatModel):
        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
            return self

    writes: list[str] = []

    @tool
    def edit_file(file_path: str) -> str:
        """Edit a project file."""
        writes.append(file_path)
        return "edited"

    service, owner, _ = workflow
    model = Model(
        responses=[
            AIMessage(
                "",
                tool_calls=[
                    {
                        "id": "premature",
                        "name": "edit_file",
                        "args": {"file_path": "/workspace/file"},
                    }
                ],
            ),
            AIMessage("blocked"),
        ]
    )
    graph = create_deep_agent(
        model=model,
        tools=[edit_file, *build_work_mode_tools(service, "expert")],
        middleware=[WorkModeMiddleware(service, "expert")],
    )
    result = await graph.ainvoke(
        {"messages": [HumanMessage("Fix this bug")]},
        config={"configurable": config(owner, "debug")},
    )
    assert not writes
    response = next(
        item
        for item in result["messages"]
        if isinstance(item, ToolMessage) and item.tool_call_id == "premature"
    )
    assert response.status == "error"
    assert "diagnosis" in response.content
    assert service.begin(owner, "expert", config(owner, "debug"))["status"] == "in_progress"


def test_bare_operation_id_resolves_as_device_evidence(workflow: Any) -> None:
    """Models often paste operation_id from device_run; accept operation:{id}."""
    service, owner, _other = workflow
    cfg = config(owner, "agentic")
    service.begin(owner, "expert", cfg)
    op = "01OPERATIONID00000000000000"
    receipt(service, owner, f"operation:{op}", kind="device", status="completed")
    advance(service, owner, cfg, "execute", [op])
    event = advance(service, owner, cfg, "verify", [f"operation:{op}"])
    assert event["status"] == "completed"


def test_work_step_receipts_omit_work_step_tool_events(workflow: Any) -> None:
    service, owner, _other = workflow
    cfg = config(owner, "agentic")
    service.begin(owner, "expert", cfg)
    receipt(
        service,
        owner,
        "tool:work-step-call",
        kind="tool",
        status="completed",
        payload={"name": "work_step"},
    )
    device = receipt(service, owner, "operation:abc", kind="device", status="completed")
    from langgraph.config import var_child_runnable_config

    token = var_child_runnable_config.set(
        {"configurable": {**cfg, "user": owner, "agent_id": "expert", "thread_id": "thread"}}
    )
    try:
        tools = build_work_mode_tools(service, "expert")
        import json

        payload = json.loads(tools[0].invoke({}))
    finally:
        var_child_runnable_config.reset(token)
    ids = {item["event_id"] for item in payload["receipts"]}
    assert device in ids
    assert "tool:work-step-call" not in ids


def test_work_step_named_tool_is_still_rejected_as_evidence(workflow: Any) -> None:
    service, owner, _other = workflow
    cfg = config(owner, "agentic")
    service.begin(owner, "expert", cfg)
    bad = receipt(
        service,
        owner,
        "tool:work-step-call",
        kind="tool",
        status="completed",
        payload={"name": "work_step"},
    )
    with pytest.raises(OctopError, match="work_step receipts are not evidence"):
        advance(service, owner, cfg, "execute", [bad])


def test_target_bound_context_evidence_completes_agentic(workflow: Any) -> None:
    """ExecutionService.for_run writes context:{id} kind=target status=bound."""
    service, owner, _other = workflow
    cfg = config(owner, "agentic")
    service.begin(owner, "expert", cfg)
    ctx = "01TARGETCONTEXT000000000000"
    receipt(
        service,
        owner,
        f"context:{ctx}",
        kind="target",
        status="bound",
        payload={"device_id": "pc", "target_kind": "device"},
    )
    advance(service, owner, cfg, "execute", [f"context:{ctx}"])
    # bare context id must also resolve via context: prefix
    final = advance(service, owner, cfg, "verify", [ctx])
    assert final["status"] == "completed"


def test_model_request_evidence_is_rejected(workflow: Any) -> None:
    service, owner, _other = workflow
    cfg = config(owner, "agentic")
    service.begin(owner, "expert", cfg)
    bad = receipt(
        service,
        owner,
        "request:01MODELREQ000000000000000",
        kind="model",
        status="completed",
        payload={"request_id": "01MODELREQ000000000000000", "model": "gpt"},
    )
    with pytest.raises(OctopError, match="model receipts are not workflow evidence"):
        advance(service, owner, cfg, "execute", [bad])


def test_call_id_resolves_via_payload_tool_call_id(workflow: Any) -> None:
    service, owner, _other = workflow
    cfg = config(owner, "agentic")
    service.begin(owner, "expert", cfg)
    call = "call_ABC123xyz"
    receipt(
        service,
        owner,
        "tool:uuid-not-call-id",
        kind="tool",
        status="completed",
        payload={"name": "device_run", "tool_call_id": call},
    )
    advance(service, owner, cfg, "execute", [call])
    done = advance(service, owner, cfg, "verify", [call])
    assert done["status"] == "completed"


def test_work_step_tool_returns_json_on_bad_evidence(workflow: Any) -> None:
    import json

    from langgraph.config import var_child_runnable_config

    service, owner, _other = workflow
    cfg = config(owner, "agentic")
    service.begin(owner, "expert", cfg)
    token = var_child_runnable_config.set(
        {"configurable": {**cfg, "user": owner, "agent_id": "expert", "thread_id": "thread"}}
    )
    try:
        tools = build_work_mode_tools(service, "expert")
        version = service.begin(owner, "expert", cfg)["payload"]["version"]
        payload = json.loads(
            tools[0].invoke(
                {
                    "stage": "execute",
                    "version": version,
                    "status": "completed",
                    "report": "Tried to cite missing receipt",
                    "evidence_ids": ["missing-evidence-id"],
                }
            )
        )
    finally:
        var_child_runnable_config.reset(token)
    assert payload["ok"] is False
    assert payload["bad_evidence_id"] == "missing-evidence-id"
    assert "not found" in payload["error"]
