"""Offline routing of separate design and execution graphs, without LLM or device calls."""

from pathlib import Path

import pytest

from octop.infra.workflow_graphs.models import (
    AgentNode,
    ConditionNode,
    GraphDefinition,
    validate_graph,
)
from octop.infra.workflow_graphs.planning import before_context, completed_state, outgoing
from octop.infra.workflow_graphs.state import (
    BranchState,
    ConversationState,
    compare,
    inputs,
    resolve,
)

EXAMPLES = Path(__file__).resolve().parents[3] / "docs/examples/workflow-graphs"
DESIGN = "gpu-innovation-design.json"
EXECUTION = "gpu-innovation.json"


def definition(filename):
    return GraphDefinition.model_validate_json((EXAMPLES / filename).read_text("utf-8"))


def simulate(graph, results):
    """Follow real engine ports with fixture replies and process receipts."""
    state = BranchState(
        variables=graph.initial_variables,
        conversation=ConversationState(agent_id=graph.agent_id, thread_id="original-thread"),
    )
    nodes = {node.id: node for node in graph.nodes}
    node = next(node for node in graph.nodes if node.kind == "entry")
    calls, selected = [], []
    for _ in range(20):
        values = inputs(node.inputs, state)
        calls.append((node.id, values))
        if node.kind == "end":
            return calls, selected, state
        port = "next"
        if isinstance(node, ConditionNode):
            result = compare(node.operator, resolve(node.left, state), resolve(node.right, state))
            port = "true" if result else "false"
        else:
            result = results.get(node.id, node.kind)
        output = {"result": result}
        executed = None
        if isinstance(node, AgentNode):
            executed = before_context(node, state, graph.agent_id, "child-" + node.id)
            assert executed.recipe.history == "empty"
            assert executed.thread_id != state.conversation.thread_id
            output["evidence"] = {
                "delivery_id": "delivery-" + node.id,
                "thread_id": executed.thread_id,
            }
        state = completed_state(node, state, output, executed)
        assert state.conversation.thread_id == "original-thread"
        edges = outgoing(graph, node.id, port)
        assert len(edges) == 1, (node.id, port)
        edge = edges[0]
        selected.append((edge.source, edge.port, edge.target))
        node = nodes[edge.target]
    raise AssertionError("graph failed to terminate")


@pytest.mark.parametrize(
    ("filename", "node_count", "edge_count"), [(DESIGN, 5, 4), (EXECUTION, 9, 9)]
)
def test_both_graphs_are_valid_reachable_and_acyclic(filename, node_count, edge_count):
    graph = definition(filename)
    assert validate_graph(graph) == []
    assert (len(graph.nodes), len(graph.edges)) == (node_count, edge_count)
    visited, stack = set(), set()

    def visit(identity):
        assert identity not in stack, "workflow must not loop back to a previous stage"
        if identity in visited:
            return
        stack.add(identity)
        for edge in graph.edges:
            if edge.source == identity:
                visit(edge.target)
        stack.remove(identity)
        visited.add(identity)

    visit(next(node.id for node in graph.nodes if node.kind == "entry"))
    assert visited == {node.id for node in graph.nodes}
    assert not graph.schedule.enabled and graph.schedule.overlap == "skip"
    assert graph.initial_variables["validation_only"] is True


def test_budget_validation_never_selects_a_paid_advanced_model():
    models = {
        (filename, node.id): node.model.rsplit("/", 1)[-1]
        for filename in (DESIGN, EXECUTION)
        for node in definition(filename).nodes
        if isinstance(node, AgentNode)
    }
    assert models == {
        (DESIGN, "design"): "deepseek-v4.1-flash",
        (DESIGN, "review"): "deepseek-v4.1-flash",
        (EXECUTION, "implement"): "deepseek-v4.1-flash",
        (EXECUTION, "code_review"): "deepseek-v4.1-flash",
        (EXECUTION, "analyze"): "deepseek-v4.1-flash",
    }


def test_design_runs_without_capacity_and_register_receives_whole_review_wrapper():
    graph = definition(DESIGN)
    reviews = [
        {
            "task_id": "T018",
            "design_revision": "v1",
            "design_sha256": "a" * 64,
            "verdict": "approved",
        }
    ]
    calls, edges, state = simulate(
        graph,
        {
            "design": {"manifest_path": "opaque-manifest-path", "design_count": 1},
            "review": {"reviews": reviews},
            "register": {"ok": True},
        },
    )
    assert [name for name, _ in calls] == ["start", "design", "review", "register", "end"]
    assert len(edges) == 4 and all(node.kind != "condition" for node in graph.nodes)
    registration = dict(calls)["register"]
    assert registration["manifest_path"] == "opaque-manifest-path"
    assert registration["review_output"] == state.outputs["review"]
    assert registration["review_output"]["result"]["reviews"] == reviews
    assert registration["review_output"]["evidence"] == {
        "delivery_id": "delivery-review",
        "thread_id": "child-review",
    }
    nodes = {node.id: node for node in graph.nodes}
    assert registration["reviewer_model"] == nodes["review"].model
    assert nodes["register"].inputs["reviewer_model"].path is None
    assert nodes["register"].inputs["authorized_scopes"].path is None
    assert registration["authorized_scopes"] == []
    assert registration["validation_only"] is True
    assert all("capacity" not in str(values) for _, values in calls)
    assert all(
        "gpu_innovation_queue.py" not in " ".join(getattr(node, "argv", [])) for node in graph.nodes
    )


@pytest.mark.parametrize("claimed", [False, "false", 1])
def test_busy_or_unavailable_claim_ends_without_parsing_missing_candidate(claimed):
    graph = definition(EXECUTION)
    calls, edges, _ = simulate(
        graph, {"claim": {"claimed": claimed, "reason": "capacity_unavailable"}}
    )
    assert [name for name, _ in calls] == ["start", "claim", "has_claim", "end"]
    assert edges[-1] == ("has_claim", "false", "end")
    conditions = [node for node in graph.nodes if isinstance(node, ConditionNode)]
    assert len(conditions) == 1 and conditions[0].id == "has_claim"
    assert conditions[0].operator == "eq" and conditions[0].right.value is True
    assert (
        len(outgoing(graph, "has_claim", "true")) == len(outgoing(graph, "has_claim", "false")) == 1
    )


@pytest.mark.parametrize("run_status", ["ran", "failed", "preparation_failed", "review_required"])
def test_execution_reviews_before_running_and_passes_results_to_analysis_and_archive(run_status):
    graph = definition(EXECUTION)
    claim = {
        "claimed": True,
        "item": {"id": "T018", "revision": 2, "design_sha256": "a" * 64},
        "claim_token": "fixed-token",
    }
    preparation = {"prepared": run_status != "preparation_failed", "id": "T018", "revision": 2}
    review = {
        "approved": run_status not in {"preparation_failed", "review_required"},
        "task_id": "T018",
        "revision": 2,
    }
    receipt = {
        "id": "T018",
        "revision": 4 if run_status in {"ran", "failed"} else 2,
        "status": run_status,
        "receipt": "opaque-receipt",
    }
    analysis = {
        "ready": run_status != "review_required",
        "receipt": "opaque-receipt",
        "report_path": "opaque-report",
    }
    calls, edges, state = simulate(
        graph,
        {
            "claim": claim,
            "implement": preparation,
            "code_review": review,
            "run": receipt,
            "analyze": analysis,
            "archive": {"status": "simulated"},
        },
    )
    assert [name for name, _ in calls] == [
        "start",
        "claim",
        "has_claim",
        "implement",
        "code_review",
        "run",
        "analyze",
        "archive",
        "end",
    ]
    assert len(edges) == 8
    values = dict(calls)
    run = values["run"]
    assert run["operation"] == "run_prepared"
    assert (run["id"], run["revision"], run["claim_token"]) == ("T018", 2, "fixed-token")
    assert run["preparation"] == preparation and run["wait_for_capacity"] is True
    assert run["code_review_output"] == state.outputs["code_review"]
    assert run["code_review_output"]["evidence"]["delivery_id"] == "delivery-code_review"
    nodes = {node.id: node for node in graph.nodes}
    assert run["reviewer_model"] == nodes["code_review"].model
    assert nodes["run"].inputs["reviewer_model"].path is None
    assert values["analyze"]["run"] == receipt
    assert values["archive"] == {
        "operation": "archive",
        "id": "T018",
        "revision": receipt["revision"],
        "claim_token": "fixed-token",
        "analysis": analysis,
    }


def test_all_execution_edges_are_covered_by_claimed_and_not_claimed_routes():
    graph = definition(EXECUTION)
    false_route = simulate(graph, {"claim": {"claimed": False}})[1]
    true_route = simulate(
        graph,
        {
            "claim": {
                "claimed": True,
                "item": {"id": "T018", "revision": 2},
                "claim_token": "token",
            },
            "implement": {"prepared": False},
            "code_review": {"approved": False},
            "run": {"id": "T018", "revision": 2, "status": "preparation_failed"},
            "analyze": {"ready": False},
        },
    )[1]
    assert set(false_route + true_route) == {
        (edge.source, edge.port, edge.target) for edge in graph.edges
    }


@pytest.mark.parametrize("filename", [DESIGN, EXECUTION])
def test_cards_do_not_overlap(filename):
    graph = definition(filename)

    def bounds(node):
        height = (
            194
            if node.kind == "agent"
            else 196
            if node.kind == "condition"
            else 112
            if node.kind == "end"
            else 168
        )
        return node.position.x, node.position.y, node.position.x + 272, node.position.y + height

    for index, left in enumerate(graph.nodes):
        lx, ly, lr, lb = bounds(left)
        for right in graph.nodes[index + 1 :]:
            rx, ry, rr, rb = bounds(right)
            assert lr <= rx or rr <= lx or lb <= ry or rb <= ly, (left.id, right.id)
