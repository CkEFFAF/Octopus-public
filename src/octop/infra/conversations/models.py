"""Validated contracts shared by HTTP, the worker and Agent tools."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetadataSettings(Contract):
    revision: int = Field(default=0, ge=0)
    title_enabled: bool = True
    brief_enabled: bool = True
    title_model: str = Field(default="account", max_length=300)
    brief_model: str = Field(default="same", max_length=300)


class SettingsPut(MetadataSettings):
    pass


class ModelOption(Contract):
    value: str
    label: str


class SettingsView(MetadataSettings):
    models: list[ModelOption] = Field(default_factory=list)
    resolved_title_model: str | None = None
    resolved_brief_model: str | None = None
    title_available: bool = False
    brief_available: bool = False


class SourceRef(Contract):
    kind: Literal["message", "run", "plan", "invocation", "resource", "event", "manual"]
    id: str = Field(min_length=1, max_length=300)
    revision: int | None = None


class BriefItem(Contract):
    text: str = Field(min_length=1, max_length=800)
    source_refs: list[SourceRef] = Field(min_length=1, max_length=8)


class SemanticItem(BriefItem):
    kind: Literal["decision", "finding", "blocker", "verification", "progress", "request"]


class GeneratedBrief(Contract):
    one_liner: str = Field(max_length=240)
    objective: str = Field(max_length=1000)
    scope: str = Field(default="", max_length=1000)
    stage: str = Field(default="", max_length=100)
    constraints: list[BriefItem] = Field(default_factory=list, max_length=12)
    completed: list[BriefItem] = Field(default_factory=list, max_length=12)
    in_progress: list[BriefItem] = Field(default_factory=list, max_length=12)
    remaining: list[BriefItem] = Field(default_factory=list, max_length=16)
    blockers: list[BriefItem] = Field(default_factory=list, max_length=12)
    next_actions: list[BriefItem] = Field(default_factory=list, max_length=8)
    decisions: list[BriefItem] = Field(default_factory=list, max_length=16)
    findings: list[BriefItem] = Field(default_factory=list, max_length=16)
    events: list[SemanticItem] = Field(default_factory=list, max_length=16)
    new_objective: bool = False


class GeneratedTitle(Contract):
    title: str = Field(min_length=1, max_length=40)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        text = value.strip()
        if (
            not text
            or any(mark in text for mark in ("\n", "\r", "`", "<", ">", "#"))
            or text[0] in {'"', "'", "“"}
        ):
            raise ValueError("METADATA_INVALID_OUTPUT")
        return text


class BriefPatch(Contract):
    expected_revision: int = Field(ge=0)
    objective: str | None = Field(default=None, max_length=1000)
    scope: str | None = Field(default=None, max_length=1000)
    note: str | None = Field(default=None, max_length=3000)
    work_state: (
        Literal["in_progress", "blocked", "ready_for_review", "completed", "cancelled"] | None
    ) = None


class MetadataJobRequest(Contract):
    kind: Literal["title", "brief"] = "brief"
    command_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class HistoryBatchRequest(Contract):
    command_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    agent_id: str | None = Field(default=None, min_length=1, max_length=300)
    thread_ids: list[str] | None = Field(default=None, min_length=1, max_length=50)


class HistoryBatchView(Contract):
    failures: list[dict[str, Any]] = Field(default_factory=list)
    errors: dict[str, int] = Field(default_factory=dict)
    batch_id: str
    total: int = 0
    queued: int = 0
    running: int = 0
    ready: int = 0
    failed: int = 0
    cancelled: int = 0


class TitleAction(Contract):
    expected_revision: int = Field(ge=0)
    action: Literal["apply", "restore"]
    title: str | None = Field(default=None, max_length=40)


class DigestRequest(Contract):
    window: str = Field(default="today", max_length=80)


class JobView(Contract):
    job_id: str
    kind: str
    status: str
    attempts: int
    error_code: str
    result: dict[str, Any] = Field(default_factory=dict)
    updated_at: float


class Coverage(Contract):
    message_seq: int = 0
    message_offset: int = 0
    archive_seq: int = 0
    archive_offset: int = 0
    archive_revision: int = 0
    event_seq: int = 0
    complete: bool = False
    history_status: str = "ready"
    truncated_sources: bool = False


class ConversationBrief(Contract):
    schema_version: int = 1
    thread_id: str
    revision: int
    objective_version: int = 1
    title: str | None
    title_source: str
    title_revision: int
    suggested_title: str | None = None
    overview: dict[str, Any]
    progress: dict[str, Any]
    decisions: list[BriefItem] = Field(default_factory=list)
    findings: list[BriefItem] = Field(default_factory=list)
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    manual_overrides: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any]


class EventView(Contract):
    event_id: str
    kind: str
    occurred_at: float
    recorded_at: float
    text: str = ""
    source_refs: list[SourceRef] = Field(default_factory=list)
    author_kind: str = "runtime"
    details: dict[str, Any] = Field(default_factory=dict)


class EventPage(Contract):
    events: list[EventView]
    next_cursor: str | None = None
    from_ts: float
    to_ts: float
    timezone: str
    coverage: Coverage


class SourceView(Contract):
    kind: str
    id: str
    text: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class DigestResult(Contract):
    digest_id: str
    window: str
    from_ts: float
    to_ts: float
    timezone: str
    summary: str = Field(max_length=4000)
    event_ids: list[str] = Field(default_factory=list)
    coverage: Coverage
    source_revision: int
    generated_at: float
    effective_model_ref: str | None = None
    freshness: str = "current"


class GeneratedDigest(Contract):
    summary: str = Field(min_length=1, max_length=4000)
    event_ids: list[str] = Field(max_length=200)
