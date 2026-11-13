"""Pydantic models for independent work items (0043 contract surface)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

WORK_ITEM_SCHEMA_VERSION = 1
WORK_ITEM_STATUSES = frozenset(
    {
        "queued",
        "running",
        "waiting_input",
        "waiting_review",
        "blocked",
        "failed",
        "completed",
        "cancelled",
        "unknown",
    }
)
TASK_CHANGED_REASONS = frozenset(
    {
        "created",
        "running",
        "progress",
        "waiting",
        "blocked",
        "completed",
        "failed",
        "cancelled",
        "unknown",
    }
)
OPEN_STATUS_GROUP = frozenset(
    {
        "queued",
        "running",
        "waiting_input",
        "waiting_review",
        "blocked",
        "unknown",
    }
)


class ExecutionTarget(BaseModel):
    target_kind: str = "device"
    device_id: str | None = None
    working_dir: str | None = None


class ResourceRef(BaseModel):
    resource_id: str
    version: int | str


class WorkItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str = Field(min_length=1, max_length=128)
    agent_id: str = Field(min_length=1, max_length=128)
    origin_thread_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    instructions: str = Field(default="", max_length=100_000)
    execution: ExecutionTarget = Field(default_factory=ExecutionTarget)
    resources: list[ResourceRef] = Field(default_factory=list)
    schema_version: int = WORK_ITEM_SCHEMA_VERSION


class WorkItemInputCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=50_000)
    target_run_id: str | None = None
    target_attempt_id: str | None = None
    schema_version: int = WORK_ITEM_SCHEMA_VERSION


class WorkItemCancel(BaseModel):
    command_id: str = Field(min_length=1, max_length=128)
    scope: Literal["task", "attempt"] = "task"
    attempt_id: str | None = None
    schema_version: int = WORK_ITEM_SCHEMA_VERSION


def create_fingerprint(body: WorkItemCreate) -> dict[str, Any]:
    """Semantic payload used for command_id conflict detection."""
    return {
        "agent_id": body.agent_id.strip(),
        "origin_thread_id": body.origin_thread_id.strip(),
        "title": body.title.strip(),
        "instructions": body.instructions,
        "execution": body.execution.model_dump(),
        "resources": [r.model_dump() for r in body.resources],
    }
