"""Serializable branch state and bounded value bindings, without expression evaluation."""

from __future__ import annotations

import copy
import re
from typing import Any, Literal

from pydantic import Field

from octop.infra.workflow_graphs.models import MAX_STATE_BYTES, Binding, Model, bounded_json


class ContextRecipe(Model):
    history: Literal["full", "recent", "empty"] = "full"
    recent_turns: int = Field(default=8, ge=1, le=100)
    inject: str = ""


class ConversationState(Model):
    agent_id: str
    thread_id: str
    recipe: ContextRecipe = Field(default_factory=ContextRecipe)


class ForkFrame(Model):
    group_id: str
    fork_id: str
    join_id: str
    branch: str
    branches: list[str]
    origin: ConversationState


class BranchState(Model):
    variables: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    event: Any = None
    conversation: ConversationState
    forks: list[ForkFrame] = Field(default_factory=list)

    def bounded(self) -> str:
        return bounded_json(self.model_dump(mode="json"), MAX_STATE_BYTES, "branch state")

    def clone(self) -> BranchState:
        return self.model_copy(deep=True)


def resolve(binding: Binding, state: BranchState) -> Any:
    if binding.path is None:
        return copy.deepcopy(binding.value)
    parts = re.findall(r"[^.\[\]]+", binding.path[2:])
    source: Any = {"vars": state.variables, "outputs": state.outputs, "event": state.event}
    for part in parts:
        if isinstance(source, dict) and part in source:
            source = source[part]
        elif isinstance(source, list) and part.isdecimal() and int(part) < len(source):
            source = source[int(part)]
        else:
            raise ValueError(f"binding is unavailable: {binding.path}")
    return copy.deepcopy(source)


def inputs(bindings: dict[str, Binding], state: BranchState) -> dict[str, Any]:
    return {name: resolve(binding, state) for name, binding in bindings.items()}


def assign(bindings: dict[str, Binding], state: BranchState) -> BranchState:
    updated = state.clone()
    values = inputs(bindings, updated)
    updated.variables.update(values)
    updated.bounded()
    return updated


def compare(operator: str, left: Any, right: Any) -> bool:
    if operator == "truthy":
        return bool(left)
    if operator == "eq":
        if type(left) in (int, float) and type(right) in (int, float):
            return bool(left == right)
        if type(left) is not type(right):
            return False
        if isinstance(left, dict):
            return left.keys() == right.keys() and all(
                compare("eq", value, right[key]) for key, value in left.items()
            )
        if isinstance(left, list):
            return len(left) == len(right) and all(
                compare("eq", a, b) for a, b in zip(left, right, strict=True)
            )
        return bool(left == right)
    if operator == "ne":
        return not compare("eq", left, right)
    if operator == "contains":
        if not isinstance(left, (str, list, dict)):
            raise ValueError("contains requires text, an array or an object")
        try:
            return right in left
        except TypeError as exc:
            raise ValueError("contains operands are incompatible") from exc
    if type(left) not in (int, float) or type(right) not in (int, float):
        raise ValueError("ordered comparisons require numbers")
    if operator == "gt":
        return bool(left > right)
    if operator == "gte":
        return bool(left >= right)
    if operator == "lt":
        return bool(left < right)
    if operator == "lte":
        return bool(left <= right)
    raise ValueError("unsupported comparison")
