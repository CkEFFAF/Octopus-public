"""Typed, bounded HTTP inspection schemas, excluding private worker credentials."""

from typing import Any

from pydantic import BaseModel, Field

from octop.infra.workflow_graphs.models import GraphDefinition, Issue
from octop.infra.workflow_graphs.state import BranchState, ConversationState


class GraphSummary(BaseModel):
    graph_id: str
    name: str
    revision: int
    published_revision: int | None
    updated_at: float


class ActivationSummary(BaseModel):
    id: str
    node_id: str
    kind: str
    ordinal: int
    status: str
    error: str
    created_at: float
    parent_id: str = ""
    incoming_edge: str = ""
    group_id: str = ""
    branch_id: str = ""
    next_at: float | None = None
    updated_at: float = 0


class ActivationView(ActivationSummary):
    input: Any = None
    output: dict[str, Any] | None = None
    before: ConversationState | None = None
    after: BranchState | None = None
    evidence: dict[str, Any] | None = None


class RunView(BaseModel):
    id: str
    graph_id: str
    version: int
    status: str
    steps: int
    max_steps: int
    max_parallel: int
    deadline: float
    pause_requested: int
    cancel_requested: int
    error: str
    created_at: float
    updated_at: float
    node_states: list[ActivationSummary] = Field(default_factory=list)


class ResultPage[T](BaseModel):
    items: list[T]
    total: int


class ValidationReport(BaseModel):
    definition: GraphDefinition
    issues: list[Issue]
