"""Declarative workflow definitions and explicit runtime context boundaries."""

from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)

MAX_DEFINITION_BYTES = 512 * 1024
MAX_INITIAL_BYTES = 64 * 1024
MAX_STATE_BYTES = 512 * 1024
MAX_INPUT_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 32 * 1024
MAX_CONTEXT_BYTES = 32 * 1024
_PATH = re.compile(r"^\$\.(?:vars|outputs|event)(?:\.[^\[\].\s]+|\[\d+\])*$")
Identifier = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")]


def bounded_json(value: Any, maximum: int, label: str) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(text.encode("utf-8")) > maximum:
        raise ValueError(f"{label} exceeds {maximum} UTF-8 bytes")
    return text


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Binding(Model):
    path: str | None = Field(default=None, max_length=500)
    value: Any = None

    @model_serializer
    def serialize(self) -> dict[str, Any]:
        return {"path": self.path} if self.path is not None else {"value": self.value}

    @model_validator(mode="after")
    def one_source(self) -> Binding:
        if ("path" in self.model_fields_set) == ("value" in self.model_fields_set):
            raise ValueError("a binding requires exactly one path or literal value")
        if "path" in self.model_fields_set and (
            self.path is None or not _PATH.fullmatch(self.path)
        ):
            raise ValueError("binding path must address $.vars, $.outputs or $.event")
        bounded_json(self.value, MAX_INPUT_BYTES, "binding literal")
        return self


class Position(Model):
    x: float = Field(default=0, ge=-1_000_000, le=1_000_000)
    y: float = Field(default=0, ge=-1_000_000, le=1_000_000)


class BeforeContext(Model):
    session: Literal["current", "new"] = "current"
    history: Literal["inherit", "recent", "empty"] = "inherit"
    recent_turns: int = Field(default=8, ge=1, le=100)
    inject: str | None = Field(default=None, max_length=MAX_CONTEXT_BYTES)
    inject_from: Binding | None = None

    @model_validator(mode="after")
    def exclusive_injection(self) -> BeforeContext:
        if self.inject is not None and self.inject_from is not None:
            raise ValueError("choose inject or inject_from")
        return self

    @field_validator("inject")
    @classmethod
    def context_bytes(cls, value: str | None) -> str | None:
        if value is not None and len(value.encode("utf-8")) > MAX_CONTEXT_BYTES:
            raise ValueError("injected context exceeds 32768 UTF-8 bytes")
        return value


class AfterContext(Model):
    session: Literal["keep", "restore"] = "restore"
    context: Literal["keep", "restore"] = "restore"


class ContextPolicy(Model):
    before: BeforeContext = Field(default_factory=BeforeContext)
    after: AfterContext = Field(default_factory=AfterContext)


class BaseNode(Model):
    id: Identifier
    label: str = Field(min_length=1, max_length=120)
    position: Position = Field(default_factory=Position)
    inputs: dict[str, Binding] = Field(default_factory=dict, max_length=32)
    assign: dict[str, Binding] = Field(default_factory=dict, max_length=32)

    @field_validator("label")
    @classmethod
    def valid_label(cls, value: str) -> str:
        if not value.strip() or any(char in value for char in "\r\n\x00"):
            raise ValueError("node label must be nonempty and single-line")
        return value.strip()


class BoundaryNode(BaseNode):
    kind: Literal["entry", "end"]


class AgentNode(BaseNode):
    kind: Literal["agent"] = "agent"
    agent_id: str = Field(default="", max_length=80)
    prompt: str = Field(default="", max_length=32000)
    model: str = Field(default="", max_length=200)
    output_mode: Literal["text", "json"] = "text"
    context: ContextPolicy = Field(default_factory=ContextPolicy)
    timeout_seconds: int = Field(default=600, ge=10, le=3600)


class ScriptNode(BaseNode):
    kind: Literal["script"] = "script"
    argv: list[Annotated[str, Field(max_length=8192)]] = Field(default_factory=list, max_length=64)
    execution_context_id: str = Field(default="", max_length=80)
    cwd: str = Field(default="", max_length=4096)
    env: dict[str, str] = Field(default_factory=dict, max_length=64)
    callback_node: str = Field(default="", max_length=80)
    output_mode: Literal["text", "json"] = "text"

    @field_validator("env")
    @classmethod
    def environment(cls, value: dict[str, str]) -> dict[str, str]:
        if any(
            not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", key) or "\x00" in text
            for key, text in value.items()
        ):
            raise ValueError("invalid script environment")
        return value


class ConditionNode(BaseNode):
    kind: Literal["condition"] = "condition"
    left: Binding = Field(default_factory=lambda: Binding(value=True))
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "contains", "truthy"] = "truthy"
    right: Binding = Field(default_factory=lambda: Binding(value=True))


class EventNode(BaseNode):
    kind: Literal["event"] = "event"
    event_type: str = Field(default="event.ready", min_length=1, max_length=100)
    purpose: str = Field(default="", max_length=2000)
    expires_in: int = Field(default=604800, ge=60, le=2592000)


class WaitEventNode(BaseNode):
    kind: Literal["wait_event"] = "wait_event"
    event_node: str = Field(default="", max_length=80)


class WaitTimeNode(BaseNode):
    kind: Literal["wait_time"] = "wait_time"
    seconds: int = Field(default=60, ge=1, le=2592000)


class ForkNode(BaseNode):
    kind: Literal["fork"] = "fork"
    join_id: str = Field(default="", max_length=80)


class JoinNode(BaseNode):
    kind: Literal["join"] = "join"
    fork_id: str = Field(default="", max_length=80)
    context_branch: str = Field(default="", max_length=80)
    merge: dict[str, dict[str, Binding]] = Field(default_factory=dict, max_length=32)


Node = Annotated[
    BoundaryNode
    | AgentNode
    | ScriptNode
    | ConditionNode
    | EventNode
    | WaitEventNode
    | WaitTimeNode
    | ForkNode
    | JoinNode,
    Field(discriminator="kind"),
]


class Edge(Model):
    id: Identifier
    source: Identifier
    target: Identifier
    port: Literal["next", "true", "false", "error"] = "next"
    label: str = Field(default="", max_length=120)


class Limits(Model):
    max_steps: int = Field(default=100, ge=1, le=1000)
    max_seconds: int = Field(default=86400, ge=60, le=2592000)
    max_parallel: int = Field(default=4, ge=1, le=4)


class Schedule(Model):
    cron: str = Field(min_length=1, max_length=100)
    timezone: str = Field(default="", max_length=100)
    overlap: Literal["skip", "parallel"] = "skip"
    enabled: bool = True

    @field_validator("cron")
    @classmethod
    def valid_cron(cls, value: str) -> str:
        CronTrigger.from_crontab(value, timezone="UTC")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        if value:
            try:
                ZoneInfo(value)
            except (ValueError, KeyError) as exc:
                raise ValueError("invalid IANA timezone") from exc
        return value


class GraphDefinition(Model):
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    agent_id: str = Field(default="", max_length=80)
    origin_thread_id: str = Field(default="", max_length=80)
    execution_context_id: str = Field(default="", max_length=80)
    initial_variables: dict[str, Any] = Field(default_factory=dict)
    nodes: list[Node] = Field(default_factory=list, max_length=64)
    edges: list[Edge] = Field(default_factory=list, max_length=128)
    limits: Limits = Field(default_factory=Limits)
    schedule: Schedule | None = None
    event_start: bool = False

    @model_validator(mode="after")
    def size_and_identifiers(self) -> GraphDefinition:
        if len({node.id for node in self.nodes}) != len(self.nodes):
            raise ValueError("duplicate node ID")
        if len({edge.id for edge in self.edges}) != len(self.edges):
            raise ValueError("duplicate edge ID")
        bounded_json(self.initial_variables, MAX_INITIAL_BYTES, "initial variables")
        bounded_json(self.model_dump(mode="json"), MAX_DEFINITION_BYTES, "graph definition")
        return self


class Issue(Model):
    message: str
    node_id: str = ""
    edge_id: str = ""


def validate_graph(graph: GraphDefinition) -> list[Issue]:
    """Drafts may be incomplete; publication requires a complete executable graph."""
    issues: list[Issue] = []
    nodes = {node.id: node for node in graph.nodes}
    outgoing: dict[str, list[Edge]] = {key: [] for key in nodes}
    entries = [node for node in graph.nodes if node.kind == "entry"]
    if len(entries) != 1:
        issues.append(Issue(message="graph requires exactly one entry"))
    if not graph.agent_id:
        issues.append(Issue(message="graph requires a default expert"))
    for edge in graph.edges:
        if edge.source not in nodes or edge.target not in nodes:
            issues.append(Issue(message="edge references a missing node", edge_id=edge.id))
            continue
        outgoing[edge.source].append(edge)
        source = nodes[edge.source]
        ports = {"true", "false", "error"} if source.kind == "condition" else {"next", "error"}
        if source.kind == "end" or edge.port not in ports:
            issues.append(Issue(message="edge uses an invalid outcome port", edge_id=edge.id))
    for node in graph.nodes:
        edges = outgoing[node.id]
        if node.kind not in {"end", "condition", "fork"} and not any(
            e.port == "next" for e in edges
        ):
            issues.append(Issue(message="node requires a next connection", node_id=node.id))
        if node.kind == "condition" and not {"true", "false"}.issubset({e.port for e in edges}):
            issues.append(
                Issue(message="condition requires true and false connections", node_id=node.id)
            )
        for port in {edge.port for edge in edges}:
            if sum(edge.port == port for edge in edges) > 1 and not (
                node.kind == "fork" and port == "next"
            ):
                issues.append(Issue(message="outcome has more than one target", node_id=node.id))
        if isinstance(node, AgentNode) and not node.prompt.strip():
            issues.append(Issue(message="Agent node requires a prompt", node_id=node.id))
        if isinstance(node, ScriptNode) and (
            not node.argv or any("\x00" in arg for arg in node.argv)
        ):
            issues.append(Issue(message="script node requires a valid argv", node_id=node.id))
        if isinstance(node, ScriptNode) and not (
            node.execution_context_id or graph.execution_context_id
        ):
            issues.append(
                Issue(message="script node requires an explicit execution context", node_id=node.id)
            )
        if (
            isinstance(node, ScriptNode)
            and node.callback_node
            and not isinstance(nodes.get(node.callback_node), EventNode)
        ):
            issues.append(Issue(message="callback source must be an event node", node_id=node.id))
        if isinstance(node, WaitEventNode) and not isinstance(
            nodes.get(node.event_node), EventNode
        ):
            issues.append(
                Issue(message="wait requires an event-registration source", node_id=node.id)
            )
        if isinstance(node, ForkNode):
            join = nodes.get(node.join_id)
            if not isinstance(join, JoinNode) or join.fork_id != node.id:
                issues.append(Issue(message="fork requires a paired join", node_id=node.id))
            if sum(edge.port == "next" for edge in edges) < 2:
                issues.append(Issue(message="fork requires at least two branches", node_id=node.id))
        if isinstance(node, JoinNode):
            fork = nodes.get(node.fork_id)
            if not isinstance(fork, ForkNode) or fork.join_id != node.id:
                issues.append(Issue(message="join requires a paired fork", node_id=node.id))
    for source in (node for node in graph.nodes if isinstance(node, EventNode)):
        if (
            sum(
                isinstance(node, WaitEventNode) and node.event_node == source.id
                for node in graph.nodes
            )
            > 1
        ):
            issues.append(
                Issue(message="an event registration has one consuming wait", node_id=source.id)
            )
    if len(entries) == 1:
        seen: set[str] = set()
        frontier = [entries[0].id]
        while frontier:
            current = frontier.pop()
            if current in seen:
                continue
            seen.add(current)
            frontier.extend(edge.target for edge in outgoing.get(current, []))
        for node in graph.nodes:
            if node.id not in seen:
                issues.append(Issue(message="node is unreachable from entry", node_id=node.id))
        if not any(nodes[key].kind == "end" for key in seen if key in nodes):
            issues.append(Issue(message="entry cannot reach an end node"))
    for fork in (node for node in graph.nodes if isinstance(node, ForkNode)):
        regions: list[set[str]] = []
        branches = [edge for edge in outgoing[fork.id] if edge.port == "next"]
        for edge in branches:
            region: set[str] = set()
            frontier = [edge.target]
            reached = False
            while frontier:
                current = frontier.pop()
                if current == fork.join_id:
                    reached = True
                    continue
                if current in region or current not in nodes:
                    continue
                region.add(current)
                frontier.extend(item.target for item in outgoing[current])
            if not reached or fork.id in region or any(nodes[key].kind == "end" for key in region):
                issues.append(
                    Issue(
                        message="fork branch must remain inside its matching join region",
                        edge_id=edge.id,
                    )
                )
            if any(region & previous for previous in regions):
                issues.append(
                    Issue(message="fork branches cross before their join", edge_id=edge.id)
                )
            if any(
                isinstance(candidate, JoinNode) and candidate.fork_id not in region
                for candidate in (nodes[key] for key in region)
            ):
                issues.append(
                    Issue(message="branch crosses a different fork region", edge_id=edge.id)
                )
            regions.append(region)
        join = nodes.get(fork.join_id)
        if isinstance(join, JoinNode):
            branch_ids = {edge.id for edge in branches}
            if (
                not set(join.merge) <= branch_ids
                or join.context_branch
                and join.context_branch not in branch_ids
            ):
                issues.append(Issue(message="join references an unknown branch", node_id=join.id))
            assigned = [key for mappings in join.merge.values() for key in mappings]
            if len(set(assigned)) != len(assigned):
                issues.append(
                    Issue(
                        message="join branches assign conflicting variable names", node_id=join.id
                    )
                )
    return issues
