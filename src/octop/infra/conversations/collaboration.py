"""Trusted conversation provenance, independent of user supplied message text."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
from typing import Any, Literal

from octop.infra.db.repos.threads import ThreadRow
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError

Category = Literal["user", "agent_collaboration"]
SENDER_KEY = "octop_sender"


def actor_snapshot(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
        return None
    if value["kind"] not in {"machine", "expert", "acp"}:
        return None
    if not all(isinstance(value.get(key), str) and value[key].strip() for key in ("id", "name")):
        return None
    return {key: value[key] for key in ("kind", "id", "name")}


def machine_actor(repos: RepoBundle, owner: int, credential_id: str) -> dict[str, str]:
    """Snapshot an already authenticated credential, including revoked historical keys."""
    row = repos.agent_access_key_repo.get(credential_id)
    if row is None or int(row["owner_user_id"]) != owner:
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    return {"kind": "machine", "id": credential_id, "name": str(row["name"])}


def public_metadata(metadata: Any) -> dict[str, Any]:
    value = metadata if isinstance(metadata, dict) else {}
    result: dict[str, Any] = {
        "category": "agent_collaboration"
        if value.get("category") == "agent_collaboration"
        else "user"
    }
    actor = actor_snapshot(value.get("actor"))
    if actor is not None:
        result["actor"] = actor
    source = value.get("collaboration_source")
    if isinstance(source, dict) and isinstance(source.get("kind"), str):
        result["collaboration_source"] = {
            key: source[key]
            for key in ("kind", "parent_thread_id", "runner_name", "acp_session_id", "device_id")
            if isinstance(source.get(key), str)
        }
    return result


def thread_metadata(repos: RepoBundle, rows: Sequence[ThreadRow]) -> dict[str, dict[str, Any]]:
    stored = repos.session_repo.metadata_for_threads([row.thread_id for row in rows])
    result = {}
    for row in rows:
        metadata = dict(stored.get(row.thread_id) or {})
        # Old remote sessions have credential evidence, but no actor snapshot yet.
        credential = metadata.get("credential_id")
        if metadata.get("source") == "acp-remote" and isinstance(credential, str):
            metadata.setdefault("category", "agent_collaboration")
            if not actor_snapshot(metadata.get("actor")):
                with suppress(OctopError):
                    metadata["actor"] = machine_actor(repos, row.user_id, credential)
        result[row.thread_id] = public_metadata(metadata)
    return result


def live_sender(chunk: dict[str, Any]) -> dict[str, Any]:
    """Project only server-stamped LangChain kwargs onto a public user frame."""
    if chunk.get("type") != "user":
        return chunk
    data = chunk.get("data")
    candidates = [chunk, data] if isinstance(data, dict) else [chunk]
    for candidate in candidates:
        kwargs = candidate.get("additional_kwargs")
        sender = actor_snapshot(kwargs.get(SENDER_KEY)) if isinstance(kwargs, dict) else None
        if sender:
            return {**chunk, "sender": sender}
    return chunk
