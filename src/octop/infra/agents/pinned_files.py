"""Owner-scoped bookmarks for expert content and explicit project targets."""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from octop.i18n import tr
from octop.infra.errors import ErrorCode, OctopError


class SettingsStore(Protocol):
    def get(self, key: str) -> str | None: ...

    def compare_and_set(self, key: str, expected: str | None, value: str) -> bool: ...


class PinnedFile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    scope: Literal["expert", "project"] = Field(
        description="Expert workspace or fixed project target."
    )
    path: str = Field(
        min_length=1,
        max_length=4096,
        description="Workspace relative for expert files; native path for project files.",
    )
    target_kind: Literal["device", "local"] | None = Field(
        default=None, description="Required explicitly for project files."
    )
    device_id: str | None = Field(
        default=None,
        max_length=200,
        description="Fixed device for project files. Empty never selects the host.",
    )
    working_dir: str | None = Field(
        default=None,
        max_length=4096,
        description="Fixed project directory used when authorizing a new execution context.",
    )

    @model_validator(mode="after")
    def validate_source(self) -> PinnedFile:
        if any(ord(char) < 32 for char in self.path):
            raise ValueError("invalid path")
        if self.scope == "expert":
            path = self.path.replace("\\", "/")
            if path.startswith("/") or ":" in path or ".." in path.split("/"):
                raise ValueError("expert paths must be workspace relative")
            path = str(PurePosixPath(path))
            if path == ".":
                raise ValueError("a file path is required")
            if any(
                value is not None for value in (self.target_kind, self.device_id, self.working_dir)
            ):
                raise ValueError("expert files cannot select an execution target")
            self.path = path
        elif self.target_kind is None or not self.working_dir:
            raise ValueError("project files require an explicit target and working directory")
        elif self.target_kind == "device" and not self.device_id:
            raise ValueError("device files require a device id")
        elif self.target_kind == "local" and self.device_id is not None:
            raise ValueError("local files cannot select a device")
        return self


class PinnedFiles(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(default=0, ge=0)
    files: list[PinnedFile] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def unique_ids(self) -> PinnedFiles:
        if len({item.id for item in self.files}) != len(self.files):
            raise ValueError("duplicate pinned file id")
        return self


class PinnedFilesConflict(OctopError):
    """The list changed after the caller loaded its revision."""

    def __init__(self) -> None:
        super().__init__(
            ErrorCode.SLASH_BAD_ARGS,
            tr("pinnedFiles.conflict", "en"),
            status=409,
            details={"reason": "pinned_files_conflict"},
        )

    def localized_message(self, locale: str, **kwargs: object) -> str:
        return tr("pinnedFiles.conflict", locale)


class PinnedFilesService:
    def __init__(self, manager: Any, settings: SettingsStore) -> None:
        self.manager = manager
        self.settings = settings

    def _key(self, agent_id: str, user_id: int, is_admin: bool) -> str:
        row = self.manager.get_row(agent_id)
        if row is None:
            raise OctopError.localized(ErrorCode.AGENT_NOT_FOUND)
        if not is_admin and row.user_id != user_id:
            raise OctopError.localized(ErrorCode.FORBIDDEN)
        owner = row.user_id if row.user_id is not None else user_id
        return f"pinned_files.user.{owner}.agent.{agent_id}"

    def get(self, agent_id: str, user_id: int, is_admin: bool) -> PinnedFiles:
        key = self._key(agent_id, user_id, is_admin)
        raw = self.settings.get(key)
        return PinnedFiles.model_validate_json(raw) if raw is not None else PinnedFiles()

    def save(self, agent_id: str, user_id: int, is_admin: bool, body: PinnedFiles) -> PinnedFiles:
        key = self._key(agent_id, user_id, is_admin)
        if not is_admin and any(item.target_kind == "local" for item in body.files):
            raise OctopError.localized(ErrorCode.FORBIDDEN)
        raw = self.settings.get(key)
        previous = PinnedFiles.model_validate_json(raw) if raw is not None else PinnedFiles()
        if previous.revision != body.revision:
            raise PinnedFilesConflict
        saved = body.model_copy(update={"revision": body.revision + 1})
        value = json.dumps(saved.model_dump(), ensure_ascii=False)
        if not self.settings.compare_and_set(key, raw, value):
            raise PinnedFilesConflict
        return saved
