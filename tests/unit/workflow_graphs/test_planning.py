from __future__ import annotations

import pytest

from octop.infra.workflow_graphs.models import AgentNode, Binding, Edge, ForkNode, JoinNode
from octop.infra.workflow_graphs.planning import (
    before_context,
    completed_state,
    fork_states,
    join_states,
)
from octop.infra.workflow_graphs.state import BranchState, ConversationState, compare


def state():
    return BranchState(
        variables={"goal": "improve"},
        conversation=ConversationState(agent_id="expert", thread_id="parent"),
    )


def test_new_session_can_restore_parent_while_retaining_a_portable_recipe():
    initial = state()
    node = AgentNode(
        id="analyze",
        label="Analyze",
        prompt="Analyze",
        context={
            "before": {
                "session": "new",
                "history": "recent",
                "recent_turns": 2,
                "inject": "prior findings",
            },
            "after": {"session": "restore", "context": "keep"},
        },
    )
    executed = before_context(node, initial, "expert", "child")
    updated = completed_state(node, initial, {"text": "improvement"}, executed)
    assert updated.conversation.thread_id == "parent"
    assert updated.conversation.recipe.history == "recent"
    assert updated.conversation.recipe.inject == "prior findings"
    assert initial.conversation.recipe.history == "full"
    next_node = AgentNode(id="next", label="Next", prompt="Continue")
    assert (
        before_context(next_node, updated, "expert", "parent").recipe == updated.conversation.recipe
    )


def test_current_session_cannot_switch_experts_and_empty_injection_explicitly_clears():
    initial = state()
    initial.conversation.recipe.inject = "keep"
    node = AgentNode(id="step", label="Step", prompt="Work", context={"before": {"inject": ""}})
    assert before_context(node, initial, "expert", "parent").recipe.inject == ""
    with pytest.raises(ValueError, match="current conversation"):
        before_context(node, initial, "other", "other-thread")


def test_parallel_state_is_local_and_join_has_explicit_reduction():
    initial = state()
    fork = ForkNode(id="fork", label="Fork", join_id="join")
    edges = [
        Edge(id="a", source="fork", target="evaluate-a"),
        Edge(id="b", source="fork", target="evaluate-b"),
    ]
    branches = fork_states(fork, initial, "activation-fork", edges)
    branches["a"].variables["private"] = 1
    branches["a"].outputs["evaluate-a"] = {"result": {"score": 0.9}}
    branches["b"].outputs["evaluate-b"] = {"result": {"score": 0.8}}
    branches["a"].conversation.thread_id = "child-a"
    assert "private" not in branches["b"].variables
    join = JoinNode(
        id="join",
        label="Join",
        fork_id="fork",
        merge={
            "a": {"score_a": Binding(path="$.outputs.evaluate-a.result.score")},
            "b": {"score_b": Binding(path="$.outputs.evaluate-b.result.score")},
        },
    )
    merged, output = join_states(join, initial, branches)
    assert merged.variables == {"goal": "improve", "score_a": 0.9, "score_b": 0.8}
    assert merged.conversation.thread_id == "parent"
    assert "evaluate-a" not in merged.outputs
    assert output["result"] == {"score_a": 0.9, "score_b": 0.8}
    assert not merged.forks
    with pytest.raises(ValueError, match="complete fork group"):
        join_states(join, initial, {"a": branches["a"]})


def test_iteration_updates_latest_lineage_output_without_mutating_prior_state():
    initial = state()
    node = AgentNode(
        id="evaluate",
        label="Evaluate",
        prompt="Evaluate",
        assign={
            "best": Binding(path="$.outputs.evaluate.result.score"),
        },
    )
    first = completed_state(node, initial, {"result": {"score": 0.8}})
    second = completed_state(node, first, {"result": {"score": 0.9}})
    assert first.variables["best"] == 0.8
    assert second.variables["best"] == 0.9
    assert compare("eq", 1, 1.0)
    assert not compare("eq", [True], [1])
