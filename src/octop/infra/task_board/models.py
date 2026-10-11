"""Versioned task board contract shared by HTTP, agent tools and scheduler."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["planning", "todo", "running", "done", "failed"]


class Schedule(BaseModel):
    cron: str
    timezone: str
    enabled: bool = True
    next_run: str | None = None
    last_trigger: str | None = None


class Review(BaseModel):
    reviewer: str
    scores: list[float] = Field(min_length=3, max_length=3)
    evidence: str = Field(min_length=1, max_length=20000)
    passed: bool
    created_at: str
    run_id: str
    model: str = ""
    baseline_scores: list[float] = Field(default_factory=list)
    rounds: list[dict[str, object]] = Field(default_factory=list)
    evidence_chars: int = 0
    truncated_chars: int = 0
    usage: dict[str, object] = Field(default_factory=dict)


class Run(BaseModel):
    id: str
    request_id: str
    contract: str = ""
    review: Review | None = None
    agent_id: str
    state: Literal["running", "succeeded", "failed", "interrupted"] = "running"
    started_at: str
    ended_at: str | None = None
    thread_id: str | None = None
    output: str = ""
    error: str = ""
    phase: Literal["executing", "reviewing", "finished"] = "executing"
    acceptance_error: str = ""
    attempts: list[Review] = Field(default_factory=list)


class Handover(BaseModel):
    goal: str
    progress: str
    next_step: str
    from_agent: str
    to_agent: str
    created_at: str


class BoardTask(BaseModel):
    id: str
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=20000)
    prompt: str = Field(default="", max_length=30000)
    project_id: str = ""
    agent_id: str = ""
    device_id: str = ""
    tags: list[str] = Field(default_factory=list, max_length=20)
    status: Status = "planning"
    parent_id: str = ""
    archived: bool = False
    pin: str = ""
    tag_prompt: str = ""
    goal: str = ""
    progress: str = ""
    next_step: str = ""
    handovers: list[Handover] = Field(default_factory=list)
    runs: list[Run] = Field(default_factory=list)
    review: Review | None = None
    schedule: Schedule | None = None
    created_at: str
    updated_at: str
    model: str = ""
    reviewer_model: str = ""
    acceptance: Literal["manual", "automatic"] = "manual"
    auto_repair: bool = False
    continue_session: bool = False


class BoardSnapshot(BaseModel):
    revision: int
    timezone: str
    tasks: list[BoardTask]
    tag_prefixes: dict[str, str] = Field(default_factory=dict)


class TaskDraft(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=20000)
    prompt: str = Field(default="", max_length=30000)
    project_id: str = ""
    agent_id: str = ""
    device_id: str = ""
    parent_id: str = ""
    tags: list[str] = Field(default_factory=list, max_length=20)
    model: str = ""
    reviewer_model: str = ""
    acceptance: Literal["manual", "automatic"] = "manual"
    auto_repair: bool = False
    continue_session: bool = False


class BoardAction(BaseModel):
    revision: int
    action: Literal[
        "create",
        "update",
        "move",
        "archive",
        "restore",
        "confirm",
        "handover",
        "parent",
        "schedule",
        "run",
        "cancel",
        "review",
        "tags",
        "verify",
    ]
    task_id: str = ""
    payload: dict[str, object] = Field(default_factory=dict)
