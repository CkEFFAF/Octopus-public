"""Authenticated, versioned file snapshots independent of project execution."""

from __future__ import annotations

import asyncio
import base64
import builtins
import contextlib
import hashlib
import json
import mimetypes
import os
import tempfile
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

from octop.config import DEFAULT_MAX_UPLOAD_MB, OctopConfig, upload_mb_to_bytes
from octop.infra.db.services import RepoBundle
from octop.infra.documents.attachments import MAX_BYTES, AttachmentService
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.gateway.media.inbound_store import validate_inbound_size
from octop.infra.utils.ulid import new_ulid


def denied() -> OctopError:
    return OctopError(ErrorCode.FORBIDDEN, "Resource access denied")


class ResourceService:
    def __init__(self, manager: Any) -> None:
        self.manager = manager
        self.repos: RepoBundle = manager._repos
        self.repo = self.repos.collaboration_repo
        if getattr(manager, "_resource_parse_cache", None) is None:
            manager._resource_parse_cache = (OrderedDict(), asyncio.Lock())
        self.parse_cache = manager._resource_parse_cache
        config = getattr(manager, "octop_config", None)
        self.max_bytes = (
            int(config.max_upload_bytes)
            if isinstance(config, OctopConfig)
            else upload_mb_to_bytes(DEFAULT_MAX_UPLOAD_MB)
        )

    def workspace(self, agent_id: str) -> Any:
        return self.manager.get_agent(agent_id).workspace

    async def reconcile_startup(self) -> None:
        """Verify advertised snapshots, without deleting unpublished or orphan bytes."""
        after = 0
        while True:
            with self.repos.db.connect() as conn:
                rows = conn.execute(
                    "SELECT id,owner_user_id,payload_json FROM collaboration_resources WHERE id>? ORDER BY id LIMIT 100",
                    (after,),
                ).fetchall()
            if not rows:
                return
            for row in rows:
                after = row["id"]
                resource = json.loads(row["payload_json"])
                unavailable = (
                    resource.get("publication_state") == "unavailable"
                    and resource.get("error_code") == "RESOURCE_SNAPSHOT_UNAVAILABLE"
                )
                if resource.get("publication_state") != "published" and not unavailable:
                    continue
                valid = await asyncio.to_thread(
                    self._verify_snapshot, row["owner_user_id"], resource
                )
                if valid and not unavailable or not valid and unavailable:
                    continue
                updated = {
                    **resource,
                    "publication_state": "published" if valid else "unavailable",
                    "error_code": None if valid else "RESOURCE_SNAPSHOT_UNAVAILABLE",
                }
                self.repo.save(
                    "collaboration_resources",
                    row["owner_user_id"],
                    resource["resource_id"],
                    resource.get("scope_thread_id"),
                    updated,
                    "resource.ready" if valid else "resource.unavailable",
                    event_id=f"{resource['resource_id']}:snapshot:{new_ulid()}",
                    resource_id=resource["resource_id"],
                    previous=resource,
                )

    def _verify_snapshot(self, owner: int, resource: dict[str, Any]) -> bool:
        try:
            with self._snapshot_path(owner, resource["version"]).open("rb") as stream:
                data = stream.read(self.max_bytes + 1)
            return (
                len(data) == resource["size"]
                and len(data) <= self.max_bytes
                and hashlib.sha256(data).hexdigest() == resource["version"]
            )
        except (OSError, ValueError, KeyError, OctopError):
            return False

    def scope(self, owner: int, agent: str, thread: str) -> Any:
        row = self.repos.agent_repo.get(agent)
        conversation = self.repos.thread_repo.get(thread)
        if (
            row is None
            or row.user_id != owner
            or conversation is None
            or (conversation.user_id, conversation.agent_id) != (owner, agent)
        ):
            raise denied()
        user = self.repos.user_repo.get(owner)
        if user is None or user.disabled:
            raise denied()
        return conversation

    async def register(
        self,
        owner: int,
        agent: str,
        path: str,
        *,
        thread: str | None = None,
        name: str = "",
        media_type: str = "",
        data: bytes | None = None,
        source_kind: str = "upload",
        source_device_id: str | None = None,
        source_path: str | None = None,
        source_context_id: str | None = None,
        source_context_key: str | None = None,
        published: bool = False,
    ) -> dict[str, Any]:
        row = self.repos.agent_repo.get(agent)
        if row is None or row.user_id != owner:
            raise denied()
        if thread:
            self.scope(owner, agent, thread)
        ws = self.workspace(agent)
        if data is None:
            path = AttachmentService(ws).relative_path(path)
            data = await ws.adownload_bytes(path)
        if data is None:
            raise denied()
        validate_inbound_size(data, max_bytes=self.max_bytes)
        digest = hashlib.sha256(data).hexdigest()
        # Identical source version has one identity even after reload/lazy registration.
        publication_scope = thread or "unbound"
        if published:
            from octop.infra.agents.teams.collaboration import runtime_config

            publication_scope += ":" + str(runtime_config().get("octop_invocation_id") or "direct")
            publication_scope += (
                f":{source_device_id or source_kind}:{source_context_id or 'store'}"
            )
        identity = (
            "res_"
            + hashlib.sha256(
                f"{owner}:{agent}:{source_kind}:{path}:{digest}:{publication_scope if published else 'upload'}".encode()
            ).hexdigest()[:32]
        )
        if source_kind in {"execution", "workspace"} and not published:
            identity = (
                "res_"
                + hashlib.sha256(
                    json.dumps(
                        [
                            owner,
                            agent,
                            thread,
                            source_kind,
                            source_device_id,
                            source_context_key or source_context_id,
                            source_path or path,
                            digest,
                        ]
                    ).encode()
                ).hexdigest()[:32]
            )
        existing = self.repo.get("collaboration_resources", owner, identity)
        if existing:
            if thread and existing.get("source_thread_id") not in {None, thread}:
                raise denied()
            if source_kind == "execution" and source_context_key:
                if existing.get("revoked"):
                    raise denied()
                if existing.get("source_context_id") != source_context_id:
                    updated = {**existing, "source_context_id": source_context_id}
                    self.repo.save(
                        "collaboration_resources",
                        owner,
                        identity,
                        thread,
                        updated,
                        "resource.ready",
                        event_id=f"{identity}:context:{source_context_id}",
                        resource_id=identity,
                        previous=existing,
                    )
                    return dict(updated)
            if thread and existing.get("scope_thread_id") is None:
                updated = {**existing, "scope_thread_id": thread, "source_thread_id": thread}
                self.repo.save(
                    "collaboration_resources",
                    owner,
                    identity,
                    thread,
                    updated,
                    "resource.ready",
                    event_id=f"{identity}:bound",
                    resource_id=identity,
                    previous=existing,
                )
                return dict(updated)
            return dict(existing)
        await asyncio.to_thread(self._snapshot, owner, digest, data)
        scope_thread = thread
        result_readers: list[dict[str, str]] = []
        producer_id = None
        if thread:
            from octop.infra.agents.teams.collaboration import runtime_config

            invocation = self.repo.get(
                "collaboration_invocations",
                owner,
                str(runtime_config().get("octop_invocation_id") or ""),
            )
            if invocation and (invocation["callee_agent_id"], invocation["child_thread_id"]) == (
                agent,
                thread,
            ):
                scope_thread = invocation["scope_thread_id"]
                producer_id = invocation["invocation_id"]
                if published:
                    current: dict[str, Any] | None = invocation
                    while current:
                        result_readers.append(
                            {
                                "agent_id": current["source_agent_id"],
                                "thread_id": current["source_thread_id"],
                            }
                        )
                        current = self.repo.get(
                            "collaboration_invocations",
                            owner,
                            current.get("parent_invocation_id") or "",
                        )
        resource = {
            "resource_id": identity,
            "version": digest,
            "name": name or path.replace("\\", "/").rsplit("/", 1)[-1],
            "media_type": media_type or mimetypes.guess_type(path)[0] or "application/octet-stream",
            "size": len(data),
            "source_agent_id": agent,
            "source_thread_id": thread,
            "scope_thread_id": scope_thread,
            "source_kind": source_kind,
            "source_device_id": source_device_id,
            "source_context_id": source_context_id,
            "source_path": source_path or path,
            "snapshot_locator": digest,
            "legacy_path": path if source_kind == "upload" else None,
            "parse_state": "pending",
            "publication_state": "published" if published else "registered",
            "created_at": time.time(),
            "producer_invocation_id": producer_id,
            "result_readers": result_readers,
        }
        self.repo.save(
            "collaboration_resources",
            owner,
            identity,
            scope_thread,
            resource,
            "resource.published" if published else "resource.registered",
            event_id=f"{identity}:registered",
            resource_id=identity,
        )
        return dict(resource)

    def _snapshot_path(self, owner: int, digest: str) -> Path:
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise denied()
        return Path(self.manager.paths.root) / "collaboration" / "resources" / str(owner) / digest

    def _snapshot(self, owner: int, digest: str, data: bytes) -> None:
        target = self._snapshot_path(owner, digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            existing = self._read_snapshot(owner, digest)
            if len(existing) > self.max_bytes or hashlib.sha256(existing).hexdigest() != digest:
                raise ValueError("RESOURCE_SNAPSHOT_INVALID")
            return
        descriptor, staging = tempfile.mkstemp(prefix=".stage-", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if hashlib.sha256(Path(staging).read_bytes()).hexdigest() != digest:
                raise ValueError("RESOURCE_SNAPSHOT_INVALID")
            # Same-filesystem publication: bytes exist completely before metadata.
            os.replace(staging, target)
        finally:
            with contextlib.suppress(FileNotFoundError):
                Path(staging).unlink()

    def owner_view(self, owner: int, agent: str, thread: str, identity: str) -> dict[str, Any]:
        self.scope(owner, agent, thread)
        resource = self.repo.get("collaboration_resources", owner, identity)
        if (
            resource is None
            or resource.get("revoked")
            or not (
                resource.get("scope_thread_id") == thread
                or (resource["source_agent_id"], resource.get("source_thread_id"))
                == (agent, thread)
            )
        ):
            raise denied()
        self.scope(owner, resource["source_agent_id"], resource["source_thread_id"])
        self.validate_source_authority(owner, resource)
        return dict(resource)

    def validate_source_authority(self, owner: int, resource: dict[str, Any]) -> None:
        if resource.get("source_kind") != "execution":
            return
        from octop.infra.execution.service import ExecutionService

        execution = ExecutionService(self.manager._device_service)
        context = execution.get(owner, resource["source_context_id"])
        if context.agent_id not in {None, resource["source_agent_id"]} or context.thread_id not in {
            None,
            resource["source_thread_id"],
        }:
            raise denied()
        if context.target_kind == "device":
            device = execution.devices.owned(owner, context.device_id or "")
            if (
                device.policy_revision != context.policy_revision
                or device.grant_version != context.grant_version
                or "files_read" not in device.permissions
            ):
                raise denied()
        elif context.policy_revision != execution.local_backend(owner).revision:
            raise denied()

    def authorize(
        self,
        owner: int,
        resource_id: str,
        agent: str,
        thread: str,
        invocation_id: str | None = None,
    ) -> dict[str, Any]:
        self.scope(owner, agent, thread)
        resource = self.repo.get("collaboration_resources", owner, resource_id)
        if resource is None or resource.get("revoked"):
            raise denied()
        source_agent = self.repos.agent_repo.get(resource["source_agent_id"])
        if source_agent is None or source_agent.user_id != owner:
            raise denied()
        source_thread = resource.get("source_thread_id")
        if source_thread:
            self.scope(owner, resource["source_agent_id"], source_thread)
        if resource["source_agent_id"] == agent and source_thread in {None, thread}:
            return dict(resource)
        if resource.get("publication_state") == "published" and {
            "agent_id": agent,
            "thread_id": thread,
        } in resource.get("result_readers", []):
            producer = self.repo.get(
                "collaboration_invocations", owner, resource.get("producer_invocation_id") or ""
            )
            if producer and (producer["callee_agent_id"], producer["child_thread_id"]) == (
                resource["source_agent_id"],
                source_thread,
            ):
                return dict(resource)
        invocation = self.repo.get("collaboration_invocations", owner, invocation_id or "")
        if not invocation or (invocation["callee_agent_id"], invocation["child_thread_id"]) != (
            agent,
            thread,
        ):
            raise denied()
        if not self.repo.has_grant(owner, resource, invocation_id or "", agent):
            raise denied()
        return dict(resource)

    async def assert_content_authority(self, owner: int, resource: dict[str, Any]) -> None:
        if resource.get("source_kind") == "execution":
            from octop.infra.execution.service import ExecutionService

            execution = ExecutionService(self.manager._device_service)
            context = execution.get(owner, resource["source_context_id"])
            if context.agent_id not in {
                None,
                resource["source_agent_id"],
            } or context.thread_id not in {None, resource["source_thread_id"]}:
                raise denied()
            # Rechecks current policy, grant and read capability, even for cached snapshots.
            await execution.call(
                owner, context.context_id, "fs.stat", {"path": resource["source_path"]}
            )
        # Existing upload aliases are mutable; a changed source revokes that version.
        if resource.get("legacy_path"):
            ws = self.workspace(resource["source_agent_id"])
            original = await ws.adownload_bytes(resource["legacy_path"])
            if original is None or hashlib.sha256(original).hexdigest() != resource["version"]:
                raise denied()

    async def bytes(self, owner: int, resource: dict[str, Any]) -> bytes:
        await self.assert_content_authority(owner, resource)
        try:
            data = await asyncio.to_thread(self._read_snapshot, owner, resource["version"])
        except OSError as exc:
            raise denied() from exc
        if (
            data is None
            or len(data) != resource["size"]
            or hashlib.sha256(data).hexdigest() != resource["version"]
        ):
            raise denied()
        return data

    async def content_chunks(
        self, owner: int, resource: dict[str, Any], start: int, end: int
    ) -> Any:
        """Read immutable snapshots in bounded chunks after current authority checks.

        Registration verified and atomically published the content digest. A media
        seek must not re-read/hash the complete snapshot for every byte range.
        """
        await self.assert_content_authority(owner, resource)
        path = self._snapshot_path(owner, resource["version"])
        try:
            stream = await asyncio.to_thread(path.open, "rb")
            try:
                size = await asyncio.to_thread(lambda: os.fstat(stream.fileno()).st_size)
                if size != resource["size"]:
                    raise denied()
                await asyncio.to_thread(stream.seek, start)
                remaining = end - start + 1
                while remaining > 0:
                    data = await asyncio.to_thread(stream.read, min(65536, remaining))
                    if not data:
                        raise denied()
                    remaining -= len(data)
                    yield data
            finally:
                await asyncio.to_thread(stream.close)
        except OSError as exc:
            raise denied() from exc

    def _read_snapshot(self, owner: int, version: str) -> builtins.bytes:
        with self._snapshot_path(owner, version).open("rb") as stream:
            return stream.read(self.max_bytes + 1)

    def public(self, resource: dict[str, Any], agent: str, thread: str) -> dict[str, Any]:
        keys = (
            "resource_id",
            "version",
            "name",
            "media_type",
            "size",
            "source_agent_id",
            "source_thread_id",
            "source_kind",
            "source_device_id",
            "parse_state",
            "publication_state",
            "created_at",
            "delivery_status",
            "error_code",
        )
        url = f"/api/agents/{quote(agent, safe='')}/threads/{quote(thread, safe='')}/resources/{resource['resource_id']}/content"
        return {
            **{key: resource[key] for key in keys if key in resource},
            "content_url": url,
            "download_url": url + "?download=true",
        }

    async def read(
        self,
        owner: int,
        agent: str,
        thread: str,
        *,
        resource_id: str = "",
        path: str = "",
        invocation_id: str | None = None,
        offset: int = 0,
        limit: int = 12000,
        page: int | None = None,
    ) -> dict[str, Any]:
        if not resource_id:
            # Legacy paths can register only the current expert's own inbound file.
            resource = await self.register(owner, agent, path, thread=thread)
            resource_id = resource["resource_id"]
        resource = self.authorize(owner, resource_id, agent, thread, invocation_id)
        if resource["size"] > MAX_BYTES:
            return {
                "status": "error",
                "code": "DOCUMENT_LIMIT",
                "error": "DOCUMENT_LIMIT",
                "retryable": False,
                "resource_id": resource_id,
                "version": resource["version"],
            }
        data = await self.bytes(owner, resource)

        class Snapshot:
            async def adownload_bytes(self, key: str) -> bytes:
                return data

        # Parser cache is below authorization; never cache grant decisions.
        reader = AttachmentService(Snapshot(), cache=self.parse_cache)
        # Historical Windows execution snapshots may store an absolute path as
        # their display name. Parsing uses only a synthetic inbound basename;
        # the authorized immutable snapshot above remains the byte source.
        filename = resource["name"].replace("\\", "/").rsplit("/", 1)[-1]
        result = await reader.read("inbound/" + filename, offset=offset, limit=limit, page=page)
        ready = result.get("status") == "ready"
        updated = {**resource, "parse_state": "ready" if ready else "failed"}
        if resource["parse_state"] != updated["parse_state"]:
            self.repo.save(
                "collaboration_resources",
                owner,
                resource_id,
                resource.get("scope_thread_id"),
                updated,
                "resource.ready" if ready else "resource.parse_failed",
                event_id=f"{resource_id}:parse:{new_ulid()}",
                resource_id=resource_id,
                previous=resource,
            )
        return {
            **result,
            "resource_id": resource_id,
            "version": resource["version"],
            "page_provenance": {"page": page, "page_count": result.get("page_count")},
        }

    async def publish(
        self,
        owner: int,
        agent: str,
        thread: str,
        path: str,
        context_id: str | None = None,
        *,
        modification_request_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        self.scope(owner, agent, thread)
        modification = None
        if modification_request_id:
            modification = self.repos.workbench_repo.get(owner, modification_request_id)
            if modification is None or not run_id or modification.get("run_id") != run_id:
                raise denied()
            if (
                modification is None
                or (modification.get("agent_id"), modification.get("thread_id")) != (agent, thread)
                or modification.get("state") not in {"queued", "result_available"}
            ):
                raise denied()
        device_id = None
        if context_id:
            from octop.infra.execution.service import ExecutionService

            execution = ExecutionService(self.manager._device_service)
            context = execution.get(owner, context_id)
            if (context.agent_id, context.thread_id) != (agent, thread):
                raise denied()
            device_id = context.device_id

            async def call(action: str, params: dict[str, Any]) -> dict[str, Any]:
                return cast(
                    dict[str, Any],
                    (await execution.call(owner, context_id, action, params, actor_agent_id=agent))[
                        "result"
                    ],
                )

            begin = await call("fs.download.begin", {"path": path})
            transfer_id = begin["transfer_id"]
            try:
                if begin["size"] < 0:
                    raise ValueError("RESOURCE_SOURCE_CHANGED")
                if begin["size"] > self.max_bytes:
                    raise OctopError(
                        ErrorCode.ATTACHMENT_TOO_LARGE,
                        "resource exceeds upload limit",
                        details={"max_mb": max(1, self.max_bytes // (1024 * 1024))},
                    )
                body = bytearray()
                while len(body) < begin["size"]:
                    chunk = await call(
                        "fs.download.chunk", {"transfer_id": transfer_id, "offset": len(body)}
                    )
                    data = base64.b64decode(chunk["data_b64"], validate=True)
                    if not data or len(body) + len(data) > begin["size"]:
                        raise ValueError("RESOURCE_SOURCE_CHANGED")
                    body.extend(data)
                data = bytes(body)
                if hashlib.sha256(data).hexdigest() != begin["sha256"]:
                    raise ValueError("RESOURCE_SOURCE_CHANGED")
            finally:
                with contextlib.suppress(Exception):
                    await call("fs.download.close", {"transfer_id": transfer_id})
            kind = context.target_kind
        else:
            # Expert store access uses only BackendWorkspace's own path rules.
            if (
                not path.startswith(("outbound/", "generated/"))
                or ".." in path.split("/")
                or "\\" in path
            ):
                raise denied()
            data = await self.workspace(agent).adownload_bytes(path)
            kind = "workspace"
        resource = await self.register(
            owner,
            agent,
            path,
            thread=thread,
            data=data,
            source_kind=kind,
            source_device_id=device_id,
            source_path=path,
            source_context_id=context_id,
            published=True,
        )
        if modification is not None:
            results = [
                *modification["results"],
                {"resource_id": resource["resource_id"], "version": resource["version"]},
            ]
            updated = {
                **modification,
                "results": list({item["resource_id"]: item for item in results}.values()),
                "state": "result_available",
                "revision": modification["revision"] + 1,
            }
            if not self.repos.workbench_repo.save(
                owner,
                agent,
                thread,
                "modification_request",
                modification_request_id or "",
                updated,
                expected=modification["revision"],
            ):
                raise ValueError("MODIFICATION_RESULT_CONFLICT")
        return resource

    async def deliver(
        self,
        owner: int,
        agent: str,
        thread: str,
        resource_id: str,
        context_id: str | None,
        path: str,
        invocation_id: str | None = None,
        *,
        device_id: str | None = None,
        target_kind: str | None = None,
        working_dir: str | None = None,
        work_mode: str = "agentic",
    ) -> dict[str, Any]:
        from octop.infra.execution.service import ExecutionService

        resource = self.authorize(owner, resource_id, agent, thread, invocation_id)
        execution = ExecutionService(self.manager._device_service)
        if context_id:
            if device_id is not None or target_kind is not None or working_dir is not None:
                raise ValueError("RESOURCE_TARGET_CONFLICT")
            context = execution.get(owner, context_id)
        else:
            if not device_id and target_kind != "local":
                raise ValueError("RESOURCE_EXPLICIT_TARGET_REQUIRED")
            context = execution.resolve(
                owner,
                device_id=device_id,
                target_kind=target_kind,
                working_dir=working_dir,
                work_mode=work_mode,
                agent_id=agent,
                thread_id=thread,
                run_id="delivery:" + new_ulid(),
            )
            context_id = context.context_id
        if (context.agent_id, context.thread_id) != (agent, thread):
            raise denied()
        if work_mode in {"ask", "plan"}:
            raise ValueError("RESOURCE_DELIVERY_POLICY_DENIED")
        if resource.get("delivery_status") == "running":
            raise ValueError("RESOURCE_DELIVERY_CONFLICT")
        attempt = new_ulid()
        current = {**resource, "delivery_status": "running", "delivery_attempt_id": attempt}
        if current.get("error_code") == "RESOURCE_DELIVERY_FAILED":
            current.pop("error_code")
        if not self.repo.save(
            "collaboration_resources",
            owner,
            resource_id,
            resource.get("scope_thread_id"),
            current,
            "resource.delivery_started",
            event_id=f"delivery:{attempt}:started",
            resource_id=resource_id,
            previous=resource,
        ):
            raise ValueError("RESOURCE_DELIVERY_CONFLICT")
        transfer_id = None

        async def call(action: str, params: dict[str, Any]) -> dict[str, Any]:
            return cast(
                dict[str, Any],
                (await execution.call(owner, context_id, action, params, actor_agent_id=agent))[
                    "result"
                ],
            )

        try:
            data = await self.bytes(owner, resource)
            begin = await call(
                "fs.upload.begin", {"path": path, "size": len(data), "sha256": resource["version"]}
            )
            transfer_id = begin["transfer_id"]
            for offset in range(0, len(data), 1024 * 1024):
                chunk = data[offset : offset + 1024 * 1024]
                ack = await call(
                    "fs.upload.chunk",
                    {
                        "transfer_id": transfer_id,
                        "offset": offset,
                        "data_b64": base64.b64encode(chunk).decode(),
                    },
                )
                if ack.get("bytes_done") != offset + len(chunk):
                    raise ValueError("RESOURCE_TRANSFER_ACK_INVALID")
            ack = await call("fs.upload.commit", {"transfer_id": transfer_id})
            if (
                ack.get("sha256") != resource["version"]
                or ack.get("size") != len(data)
                or ack.get("status") != "completed"
            ):
                raise ValueError("RESOURCE_TRANSFER_CHECKSUM_MISMATCH")
            result = {
                "status": "completed",
                "resource_id": resource_id,
                "version": resource["version"],
                "target_kind": context.target_kind,
                "device_id": context.device_id,
                "size": len(data),
            }
            final = {**current, "delivery_status": "completed"}
            event = "resource.delivered"
        except Exception:
            final = {
                **current,
                "delivery_status": "failed",
                "error_code": "RESOURCE_DELIVERY_FAILED",
            }
            event = "resource.delivery_failed"
            raise
        finally:
            if transfer_id:
                with contextlib.suppress(Exception):
                    await call("fs.upload.abort", {"transfer_id": transfer_id})
            if "final" in locals() and not self.repo.save(
                "collaboration_resources",
                owner,
                resource_id,
                resource.get("scope_thread_id"),
                final,
                event,
                event_id=f"delivery:{attempt}:terminal",
                resource_id=resource_id,
                previous=current,
            ):
                raise ValueError("RESOURCE_DELIVERY_RECEIPT_CONFLICT")
        return result
