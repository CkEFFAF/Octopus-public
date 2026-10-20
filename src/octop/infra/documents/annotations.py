"""Versioned comments and durable modification requests over authorized resources."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from octop.infra.documents.resources import ResourceService, denied
from octop.infra.utils.ulid import new_ulid


class Anchor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["file", "text", "image", "page", "slide", "document", "sheet", "time"]
    quote: str = Field(default="", max_length=4000)
    line: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    end_column: int | None = Field(default=None, ge=1)
    page: int | None = Field(default=None, ge=1, le=100000)
    rect: tuple[float, float, float, float] | None = None
    sheet: str | None = Field(default=None, max_length=200)
    cells: str | None = Field(default=None, max_length=40)
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, ge=0)
    renderer: str = Field(default="workbench-v1", max_length=100)

    @model_validator(mode="after")
    def valid_anchor(self) -> Anchor:
        if self.rect:
            x, y, width, height = self.rect
            if (
                not all(math.isfinite(v) and 0 <= v <= 1 for v in self.rect)
                or x + width > 1.000001
                or y + height > 1.000001
                or width <= 0
                or height <= 0
            ):
                raise ValueError("invalid normalized region")
        if self.kind == "text" and (
            self.line is None
            or self.column is None
            or self.end_line is None
            or self.end_column is None
            or (self.end_line, self.end_column) < (self.line, self.column)
        ):
            raise ValueError("invalid text range")
        if self.kind in {"page", "slide"} and self.page is None:
            raise ValueError("page required")
        if self.kind == "image" and self.rect is None:
            raise ValueError("image region required")
        if self.kind == "document" and not self.quote:
            raise ValueError("document quote required")
        if self.kind == "sheet" and (
            not self.sheet
            or not self.cells
            or not re.fullmatch(r"[A-Z]{1,3}[1-9]\d{0,6}(?::[A-Z]{1,3}[1-9]\d{0,6})?", self.cells)
        ):
            raise ValueError("invalid sheet range")
        if self.kind == "time" and (
            self.start is None
            or self.end is None
            or not math.isfinite(self.start)
            or not math.isfinite(self.end)
            or self.end < self.start
        ):
            raise ValueError("invalid time interval")
        return self


class AnnotationService:
    def __init__(self, manager: Any) -> None:
        self.resources = ResourceService(manager)
        self.repo = self.resources.repos.workbench_repo

    def scope(self, owner: int, agent: str, thread: str, resource: str) -> dict[str, Any]:
        return self.resources.owner_view(owner, agent, thread, resource)

    def listing(
        self, owner: int, agent: str, thread: str, resource: str, after: int, limit: int
    ) -> dict[str, Any]:
        self.scope(owner, agent, thread, resource)
        rows = self.repo.list(
            owner, agent, thread, "annotation", resource=resource, after=after, limit=limit + 1
        )
        page = rows[:limit]
        return {
            "items": page,
            "has_more": len(rows) > limit,
            "next_cursor": page[-1]["cursor"] if page else after,
        }

    def create(
        self,
        owner: int,
        agent: str,
        thread: str,
        resource: str,
        version: str,
        anchor: Anchor,
        body: str,
    ) -> dict[str, Any]:
        source = self.scope(owner, agent, thread, resource)
        if source["version"] != version:
            raise ValueError("ANNOTATION_SOURCE_CONFLICT")
        now = time.time()
        value: dict[str, Any] = {
            "annotation_id": new_ulid(),
            "author": owner,
            "agent_id": agent,
            "thread_id": thread,
            "resource_id": resource,
            "version": version,
            "anchor": anchor.model_dump(exclude_none=True),
            "body": body,
            "replies": [],
            "status": "open",
            "revision": 1,
            "created_at": now,
            "updated_at": now,
            "request_ids": [],
        }
        self.repo.save(
            owner, agent, thread, "annotation", value["annotation_id"], value, resource=resource
        )
        return value

    def update(
        self,
        owner: int,
        agent: str,
        thread: str,
        resource: str,
        identity: str,
        revision: int,
        body: str | None,
        status: str | None,
        reply: str | None,
    ) -> dict[str, Any]:
        self.scope(owner, agent, thread, resource)
        old = self.repo.get(owner, identity)
        if old is None or (old.get("agent_id"), old.get("thread_id"), old.get("resource_id")) != (
            agent,
            thread,
            resource,
        ):
            raise denied()
        if old["revision"] != revision:
            raise ValueError("ANNOTATION_REVISION_CONFLICT")
        if reply and len(old["replies"]) >= 100:
            raise ValueError("ANNOTATION_REPLY_LIMIT")
        value = {**old, "revision": revision + 1, "updated_at": time.time()}
        if body is not None:
            value["body"] = body
        if status:
            value["status"] = status
        if reply:
            value["replies"] = [
                *old["replies"],
                {"body": reply, "author": owner, "created_at": time.time()},
            ]
        if not self.repo.save(
            owner, agent, thread, "annotation", identity, value, expected=revision
        ):
            raise ValueError("ANNOTATION_REVISION_CONFLICT")
        return value

    def prepare_request(
        self, owner: int, agent: str, thread: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        source = self.scope(owner, agent, thread, body["resource_id"])
        if source["version"] != body["source_version"]:
            raise ValueError("ANNOTATION_SOURCE_CONFLICT")
        fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        identity = (
            "mod_"
            + hashlib.sha256(f"{owner}:{agent}:{thread}:{body['command_id']}".encode()).hexdigest()[
                :32
            ]
        )
        old = self.repo.get(owner, identity)
        if old:
            if old["fingerprint"] != fingerprint:
                raise ValueError("ANNOTATION_COMMAND_CONFLICT")
            return old
        comments = []
        for selection in body["annotations"]:
            item = self.repo.get(owner, selection["annotation_id"])
            if item is None or (
                item.get("agent_id"),
                item.get("thread_id"),
                item.get("resource_id"),
                item.get("version"),
                item.get("revision"),
            ) != (agent, thread, source["resource_id"], source["version"], selection["revision"]):
                raise ValueError("ANNOTATION_REVISION_CONFLICT")
            comments.append(
                {
                    "annotation_id": item["annotation_id"],
                    "revision": item["revision"],
                    "anchor": item["anchor"],
                    "body": item["body"],
                }
            )
        if len({i["annotation_id"] for i in comments}) != len(comments):
            raise ValueError("ANNOTATION_DUPLICATE_SELECTION")
        value = {
            "request_id": identity,
            "agent_id": agent,
            "thread_id": thread,
            "resource_id": source["resource_id"],
            "source_version": source["version"],
            "command_id": body["command_id"],
            "fingerprint": fingerprint,
            "annotations": comments,
            "state": "pending",
            "revision": 1,
            "created_at": time.time(),
            "results": [],
        }
        value["text"] = (
            "Please revise the immutable resource according to these user comments. Read it with read_attachment(resource_id). Publish the new version with publish_artifact(modification_request_id). Do not resolve comments automatically.\n"
            + json.dumps(
                {
                    "modification_request_id": identity,
                    "resource_id": source["resource_id"],
                    "version": source["version"],
                    "comments": comments,
                },
                ensure_ascii=False,
            )
        )
        value["target"] = {
            "context_id": source.get("source_context_id"),
            "device_id": source.get("source_device_id"),
            "path": source.get("source_path"),
        }
        if not self.repo.save(
            owner,
            agent,
            thread,
            "modification_request",
            identity,
            value,
            resource=source["resource_id"],
        ):
            return self.prepare_request(owner, agent, thread, body)
        return value

    def bind_run(
        self, owner: int, agent: str, thread: str, identity: str, run_id: str
    ) -> dict[str, Any]:
        """Bind only a dispatching durable queue entry, even before HTTP acknowledgement.

        The queue worker may run to completion before the admitting HTTP handler
        resumes. Admission is proved by its durable receipt, not the later UI state.
        """
        modification = self.repo.get(owner, identity)
        if modification is None or (
            modification.get("agent_id"),
            modification.get("thread_id"),
        ) != (agent, thread):
            raise ValueError("MODIFICATION_RUN_BINDING_INVALID")
        bound_run = modification.get("run_id")
        if bound_run:
            if bound_run != run_id:
                raise ValueError("MODIFICATION_ALREADY_BOUND")
            return modification
        receipt = self.resources.repos.chat_input_repo.get(owner, modification["command_id"])
        if receipt is None or (
            receipt.get("agent_id"),
            receipt.get("thread_id"),
            receipt.get("status"),
            receipt["payload"].get("snapshot", {}).get("modification_request_id"),
        ) != (agent, thread, "dispatching", identity):
            raise ValueError("MODIFICATION_QUEUE_ADMISSION_REQUIRED")
        updated = {
            **modification,
            "state": "queued",
            "receipt": receipt,
            "run_id": run_id,
            "revision": modification["revision"] + 1,
        }
        if not self.repo.save(
            owner,
            agent,
            thread,
            "modification_request",
            identity,
            updated,
            expected=modification["revision"],
        ):
            raise ValueError("MODIFICATION_RUN_BINDING_CONFLICT")
        return updated

    def queued(self, owner: int, value: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
        current = self.repo.get(owner, value["request_id"]) or value
        if current["state"] != "pending":
            return current
        updated = {
            **current,
            "state": "queued",
            "receipt": receipt,
            "revision": current["revision"] + 1,
        }
        self.repo.save(
            owner,
            current["agent_id"],
            current["thread_id"],
            "modification_request",
            current["request_id"],
            updated,
            expected=current["revision"],
        )
        persisted = self.repo.get(owner, current["request_id"])
        if persisted is None or persisted["state"] == "pending":
            raise ValueError("MODIFICATION_ADMISSION_RETRY_REQUIRED")
        return persisted

    def requests(self, owner: int, agent: str, thread: str, resource: str) -> list[dict[str, Any]]:
        self.scope(owner, agent, thread, resource)
        return self.repo.list(owner, agent, thread, "modification_request", resource=resource)
