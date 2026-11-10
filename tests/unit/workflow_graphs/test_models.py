from __future__ import annotations

import pytest
from pydantic import ValidationError

from octop.infra.workflow_graphs.models import Binding, GraphDefinition, validate_graph
from octop.infra.workflow_graphs.state import (
    BranchState,
    ConversationState,
    assign,
    compare,
    resolve,
)


def definition(**changes):
    return GraphDefinition.model_validate(
        {
            "name": "Daily workflow",
            "agent_id": "expert",
            "nodes": [
                {"id": "start", "label": "Start", "kind": "entry"},
                {"id": "end", "label": "End", "kind": "end"},
            ],
            "edges": [{"id": "edge", "source": "start", "target": "end"}],
            **changes,
        }
    )


def test_complete_definition_and_editable_incomplete_draft():
    assert not validate_graph(definition())
    draft = definition(nodes=[], edges=[])
    assert validate_graph(draft)
    with pytest.raises(ValidationError):
        definition(nodes=[{"id": "same", "label": "A", "kind": "entry"}] * 2)
    with pytest.raises(ValidationError):
        definition(limits={"max_steps": 0})


def test_condition_routes_and_event_sources_are_validated():
    graph = definition(
        nodes=[
            {"id": "start", "label": "Start", "kind": "entry"},
            {"id": "end", "label": "End", "kind": "end"},
            {"id": "condition", "label": "Check", "kind": "condition"},
            {"id": "wait", "label": "Wait", "kind": "wait_event", "event_node": "end"},
        ]
    )
    errors = validate_graph(graph)
    assert any(
        error.node_id == "condition" and "true and false" in error.message for error in errors
    )
    assert any(
        error.node_id == "wait" and "event-registration" in error.message for error in errors
    )


def test_bindings_are_explicit_bounded_json_and_never_expressions():
    for value in ({}, {"path": "$.vars.x", "value": 1}, {"path": "__import__('os')"}):
        with pytest.raises(ValidationError):
            Binding.model_validate(value)
    assert Binding(value=None).value is None
    state = BranchState(
        variables={"目标": [7]},
        outputs={"evaluate": {"result": {"score": 0.8}}},
        conversation=ConversationState(agent_id="expert", thread_id="thread"),
    )
    assert resolve(Binding(path="$.vars.目标[0]"), state) == 7
    assert resolve(Binding(path="$.outputs.evaluate.result.score"), state) == 0.8
    changed = assign({"best": Binding(path="$.outputs.evaluate.result.score")}, state)
    assert changed.variables["best"] == 0.8 and "best" not in state.variables
    with pytest.raises(ValueError, match="unavailable"):
        resolve(Binding(path="$.vars.missing"), state)


def test_comparisons_do_not_coerce_booleans_or_execute_code():
    assert compare("gt", 0.9, 0.8)
    assert not compare("eq", True, 1)
    assert compare("contains", [1, 2], 1)
    with pytest.raises(ValueError):
        compare("gt", "2", 1)
    with pytest.raises(ValueError):
        definition(initial_variables={"bad": float("nan")})
