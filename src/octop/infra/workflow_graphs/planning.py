"""Pure graph transitions, branch-local bindings and portable context recipes."""

from __future__ import annotations

import copy
import json
from typing import Any

from octop.infra.workflow_graphs.models import (
    MAX_CONTEXT_BYTES,
    AgentNode,
    Edge,
    ForkNode,
    GraphDefinition,
    JoinNode,
    Node,
)
from octop.infra.workflow_graphs.state import (
    BranchState,
    ConversationState,
    ForkFrame,
    assign,
    inputs,
    resolve,
)


def outgoing(graph: GraphDefinition, node_id: str, port: str = "next") -> list[Edge]:
    return [edge for edge in graph.edges if edge.source == node_id and edge.port == port]


def before_context(
    node: AgentNode, state: BranchState, agent: str, thread: str
) -> ConversationState:
    policy = node.context.before
    if policy.session == "current" and (agent, thread) != (
        state.conversation.agent_id,
        state.conversation.thread_id,
    ):
        raise ValueError("current conversation must retain its expert and thread")
    recipe = state.conversation.recipe.model_copy(deep=True)
    if policy.history != "inherit":
        recipe.history = policy.history
        recipe.recent_turns = policy.recent_turns
    if policy.inject is not None:
        recipe.inject = policy.inject
    if policy.inject_from is not None:
        value = resolve(policy.inject_from, state)
        recipe.inject = (
            value
            if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False, allow_nan=False)
        )
    if len(recipe.inject.encode("utf-8")) > MAX_CONTEXT_BYTES:
        raise ValueError("resolved injected context is too large")
    return ConversationState(agent_id=agent, thread_id=thread, recipe=recipe)


def completed_state(
    node: Node,
    state: BranchState,
    output: dict[str, Any],
    executed: ConversationState | None = None,
) -> BranchState:
    updated = state.clone()
    updated.outputs[node.id] = copy.deepcopy(output)
    if isinstance(node, AgentNode) and executed is not None:
        policy = node.context.after
        session = executed if policy.session == "keep" else state.conversation
        recipe = executed.recipe if policy.context == "keep" else state.conversation.recipe
        updated.conversation = ConversationState(
            agent_id=session.agent_id,
            thread_id=session.thread_id,
            recipe=recipe.model_copy(deep=True),
        )
    return assign(node.assign, updated)


def fork_states(
    node: ForkNode,
    state: BranchState,
    activation_id: str,
    edges: list[Edge],
) -> dict[str, BranchState]:
    result = {}
    branch_ids = [edge.id for edge in edges]
    for edge in edges:
        child = state.clone()
        child.forks.append(
            ForkFrame(
                group_id=activation_id,
                fork_id=node.id,
                join_id=node.join_id,
                branch=edge.id,
                branches=branch_ids,
                origin=state.conversation.model_copy(deep=True),
            )
        )
        child.bounded()
        result[edge.id] = child
    return result


def join_states(
    node: JoinNode,
    origin: BranchState,
    arrivals: dict[str, BranchState],
) -> tuple[BranchState, dict[str, Any]]:
    if not arrivals:
        raise ValueError("join requires branch arrivals")
    frames = [state.forks[-1] for state in arrivals.values() if state.forks]
    if len(frames) != len(arrivals) or len({frame.group_id for frame in frames}) != 1:
        raise ValueError("join arrivals belong to different fork activations")
    expected = set(frames[0].branches)
    if set(arrivals) != expected or any(
        frame.join_id != node.id or frame.fork_id != node.fork_id for frame in frames
    ):
        raise ValueError("join is waiting for its complete fork group")
    merged = origin.clone()
    values: dict[str, Any] = {}
    for branch in frames[0].branches:
        selected = inputs(node.merge.get(branch, {}), arrivals[branch])
        if set(values) & set(selected):
            raise ValueError("parallel branches assign conflicting variable names")
        values.update(selected)
    merged.variables.update(copy.deepcopy(values))
    if node.context_branch:
        if node.context_branch not in arrivals:
            raise ValueError("selected context branch is unavailable")
        merged.conversation = arrivals[node.context_branch].conversation.model_copy(deep=True)
    output = {"result": values, "branches": frames[0].branches}
    # Origin is the state after the fork itself, before pushing its frame.
    merged.outputs[node.id] = copy.deepcopy(output)
    merged = assign(node.assign, merged)
    return merged, output
