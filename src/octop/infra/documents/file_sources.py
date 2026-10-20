"""Authorized file sources become immutable preview versions, never publications."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import re
from typing import Any

from octop.infra.documents.resources import ResourceService, denied
from octop.infra.execution.service import ExecutionService


def byte_range(value: str, size: int) -> tuple[int, int] | None:
    """One bounded RFC 9110 byte interval; multi-range is deliberately unsupported."""
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
    if not match or size <= 0 or not any(match.groups()):
        return None
    left, right = match.groups()
    if not left:
        count = int(right)
        return (max(0, size - count), size - 1) if count > 0 else None
    start, end = int(left), min(int(right), size - 1) if right else size - 1
    return (start, end) if 0 <= start <= end < size else None


class FileSourceService:
    def __init__(self, manager: Any) -> None:
        self.resources = ResourceService(manager)
        self.execution = ExecutionService(manager._device_service)

    async def assert_current(self, owner: int, resource: dict[str, Any]) -> None:
        if resource.get("source_kind") == "execution":
            context = resource["source_context_id"]
            session = (
                await self.execution.call(
                    owner, context, "fs.download.begin", {"path": resource["source_path"]}
                )
            )["result"]
            try:
                if session["sha256"] != resource["version"] or session["size"] != resource["size"]:
                    raise ValueError("ANNOTATION_SOURCE_CONFLICT")
            finally:
                with contextlib.suppress(Exception):
                    await self.execution.call(
                        owner, context, "fs.download.close", {"transfer_id": session["transfer_id"]}
                    )
        elif resource.get("source_kind") == "workspace" or (
            resource.get("source_kind") == "upload" and resource.get("legacy_path")
        ):
            current = await self.resources.workspace(resource["source_agent_id"]).adownload_bytes(
                resource.get("legacy_path") or resource["source_path"]
            )
            if (
                current is None
                or len(current) != resource["size"]
                or hashlib.sha256(current).hexdigest() != resource["version"]
            ):
                raise ValueError("ANNOTATION_SOURCE_CONFLICT")

    async def open(
        self, owner: int, agent: str, thread: str, source: dict[str, Any]
    ) -> dict[str, Any]:
        self.resources.scope(owner, agent, thread)
        kind = source["kind"]
        if kind == "resource":
            resource = self.resources.owner_view(owner, agent, thread, source["resource_id"])
        elif kind == "workspace":
            resource = await self.resources.register(
                owner, agent, source["path"], thread=thread, source_kind="workspace"
            )
        else:
            context_id = source["context_id"]
            context = self.execution.get(owner, context_id)
            if context.agent_id not in {None, agent} or context.thread_id not in {None, thread}:
                raise denied()
            path = source["path"]

            async def call(action: str, params: dict[str, Any]) -> dict[str, Any]:
                result = await self.execution.call(owner, context_id, action, params)
                return dict(result["result"])

            begin = await call("fs.download.begin", {"path": path})
            try:
                size = begin["size"]
                if not isinstance(size, int) or size < 0 or size > self.resources.max_bytes:
                    raise ValueError("FILE_PREVIEW_LIMIT")
                content = bytearray()
                while len(content) < size:
                    offset = len(content)
                    part = await call(
                        "fs.download.chunk", {"transfer_id": begin["transfer_id"], "offset": offset}
                    )
                    chunk = base64.b64decode(part["data_b64"], validate=True)
                    if (
                        part["offset"] != offset
                        or part["size"] != size
                        or not 0 < len(chunk) <= 1048576
                        or offset + len(chunk) > size
                        or part["eof"] != (offset + len(chunk) == size)
                    ):
                        raise ValueError("FILE_CHANGED_DURING_READ")
                    content.extend(chunk)
                if hashlib.sha256(content).hexdigest() != begin["sha256"]:
                    raise ValueError("FILE_CHANGED_DURING_READ")
                canonical_path = begin["path"]
                resource = await self.resources.register(
                    owner,
                    agent,
                    canonical_path,
                    thread=thread,
                    data=bytes(content),
                    source_kind="execution",
                    source_device_id=context.device_id,
                    source_path=canonical_path,
                    source_context_id=context_id,
                    source_context_key=json.dumps(
                        [
                            context.target_kind,
                            context.device_id,
                            context.policy_revision,
                            context.grant_version,
                        ]
                    ),
                )
            finally:
                with contextlib.suppress(Exception):
                    await call("fs.download.close", {"transfer_id": begin["transfer_id"]})
        return {
            "resource": self.resources.public(resource, agent, thread),
            "source": {
                "kind": kind,
                "version": resource["version"],
                "read": True,
                "edit": False,
                "context_id": resource.get("source_context_id"),
            },
        }
