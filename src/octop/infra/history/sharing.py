"""Owner-published, bounded and independently revocable public history snapshots."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import re
import secrets
import time
from contextlib import suppress
from typing import Any
from urllib.parse import urlsplit

from cryptography.fernet import Fernet

from octop.config import OctopConfig, validate_public_origin
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.history.reader import read_page
from octop.infra.history.service import HistoryArchive
from octop.infra.utils.llm_text import strip_thinking
from octop.infra.utils.ulid import new_ulid

MAX_SOURCE_MESSAGES = 4000
MAX_PUBLIC_MESSAGES = 2000
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024
DEFAULT_EXPIRY = 30 * 86400
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_MACHINE_SECTION = re.compile(
    r"^\s*(?:\[(?:Attachment|附件)\]\s|\[(?:image|audio)\s+offloaded\s*:)", re.I
)
_LINK = re.compile(r"(!?)\[([^\]\n]*)\]\(([^\n)]*)\)")


def canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_link(match: re.Match[str]) -> str:
    if match[1]:
        return ""
    target = match[3].strip().split(" ", 1)[0].strip("<>")
    try:
        parsed = urlsplit(target)
    except ValueError:
        return match[2]
    host = (parsed.hostname or "").lower()
    private = host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost")
    with suppress(ValueError):
        private = private or not ipaddress.ip_address(host).is_global
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or private
        or parsed.username
        or parsed.path.startswith("/api/")
        or parsed.path.startswith("/share/")
    ):
        return match[2]
    return match[0]


def public_text(content: Any) -> str:
    """Allow visible text only; remove recognized implementation/media placeholders."""
    if isinstance(content, list):
        content = "\n".join(
            part if isinstance(part, str) else part["text"]
            for part in content
            if isinstance(part, str)
            or (
                isinstance(part, dict)
                and part.get("type") == "text"
                and isinstance(part.get("text"), str)
            )
        )
    if not isinstance(content, str):
        return ""
    text = strip_thinking(content)
    parts: list[str] = []
    for part in re.split(r"\n\s*\n", text):
        if _MACHINE_SECTION.match(part):
            continue
        lines = []
        for line in part.splitlines():
            if _MACHINE_SECTION.match(line):
                continue
            try:
                dumped = json.loads(line)
            except (ValueError, TypeError):
                dumped = None
            if isinstance(dumped, dict) and dumped.get("type") in {
                "image_url",
                "image",
                "input_audio",
                "file",
                "audio",
                "video",
            }:
                continue
            lines.append(line)
        parts.append("\n".join(lines))
    text = _LINK.sub(_safe_link, "\n\n".join(parts))
    # HTML media and reference definitions must not retain private media URLs.
    text = re.sub(r"<(?:img|audio|video|source)\b[^>]*>", "", text, flags=re.I)
    text = re.sub(r"(?m)^\s*\[[^\]]+\]:\s*\S+.*$", "", text)
    return text.strip()


class ThreadSharingService:
    def __init__(
        self,
        repos: RepoBundle,
        config: OctopConfig,
        registry: Any = None,
        history_archive: HistoryArchive | None = None,
    ):
        self.repos, self.config = repos, config
        self.registry, self.archive = registry, history_archive

    def owner(self, owner: int) -> None:
        user = self.repos.user_repo.get(owner)
        if user is None or user.disabled:
            raise OctopError(ErrorCode.FORBIDDEN, "authenticated active owner required")

    def thread(self, owner: int, thread_id: str, agent_id: str | None = None) -> Any:
        self.owner(owner)
        row = self.repos.thread_repo.get(thread_id)
        if row is None or row.user_id != owner or (agent_id and row.agent_id != agent_id):
            raise OctopError(ErrorCode.NOT_FOUND, "owned conversation not found")
        return row

    async def preview(
        self, owner: int, thread_id: str, *, agent_id: str | None = None
    ) -> dict[str, Any]:
        row = await asyncio.to_thread(self.thread, owner, thread_id, agent_id)
        messages: list[dict[str, Any]] = []
        cursor = None
        scanned = 0
        while True:
            page = await read_page(
                self.archive,
                self.registry,
                row.agent_id,
                thread_id,
                limit=200,
                cursor=cursor,
                messages=self.repos.thread_message_repo,
            )
            wires = page["messages"]
            scanned += len(wires)
            if scanned > MAX_SOURCE_MESSAGES:
                raise OctopError(
                    ErrorCode.SHARE_LIMIT,
                    "Snapshot exceeds sharing limits; select a shorter conversation",
                )
            batch = []
            for wire in wires:
                if not isinstance(wire, dict):
                    continue
                kind = wire.get("type") or wire.get("role")
                if not isinstance(kind, str):
                    continue
                role = {"human": "user", "ai": "assistant"}.get(kind, kind)
                data = wire.get("data", wire)
                if role not in {"user", "assistant"} or not isinstance(data, dict):
                    continue
                text = public_text(data.get("content"))
                if text:
                    batch.append({"role": role, "content": text})
            messages = [*batch, *messages]
            if len(messages) > MAX_PUBLIC_MESSAGES:
                raise OctopError(
                    ErrorCode.SHARE_LIMIT,
                    "Snapshot exceeds sharing limits; select a shorter conversation",
                )
            # Bound memory even before final canonical numbering.
            if len(canonical({"messages": messages}).encode("utf-8")) > MAX_SNAPSHOT_BYTES:
                raise OctopError(
                    ErrorCode.SHARE_LIMIT,
                    "Snapshot exceeds sharing limits; select a shorter conversation",
                )
            if not page["has_more"]:
                break
            next_cursor = page["next_cursor"]
            if not next_cursor or next_cursor == cursor or scanned >= MAX_SOURCE_MESSAGES:
                raise OctopError(
                    ErrorCode.SHARE_LIMIT,
                    "Snapshot exceeds sharing limits; select a shorter conversation",
                )
            cursor = next_cursor
        if not messages:
            raise OctopError(ErrorCode.SHARE_INVALID, "No public text to share")
        snapshot = {
            "title": public_text(row.title or "Conversation"),
            "timezone": self.config.default_timezone,
            "messages": [{"id": i, **message} for i, message in enumerate(messages, 1)],
        }
        encoded = canonical(snapshot).encode("utf-8")
        if len(encoded) > MAX_SNAPSHOT_BYTES:
            raise OctopError(
                ErrorCode.SHARE_LIMIT,
                "Snapshot exceeds sharing limits; select a shorter conversation",
            )
        return {
            **snapshot,
            "message_count": len(messages),
            "preview_digest": hashlib.sha256(encoded).hexdigest(),
        }

    async def create(
        self,
        owner: int,
        thread_id: str,
        preview_digest: str,
        expires_in_seconds: int | None = DEFAULT_EXPIRY,
        *,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        if expires_in_seconds is not None and (
            type(expires_in_seconds) is not int or not 60 <= expires_in_seconds <= 31536000
        ):
            raise OctopError(ErrorCode.SHARE_INVALID, "Expiry must be null or 60..31536000 seconds")
        origin = validate_public_origin(self.config.public_origin)
        if not origin:
            raise OctopError(
                ErrorCode.SHARE_ORIGIN_REQUIRED,
                "Configure OCTOP_PUBLIC_ORIGIN with the external HTTPS origin",
            )
        preview = await self.preview(owner, thread_id, agent_id=agent_id)
        if not secrets.compare_digest(preview["preview_digest"], preview_digest):
            raise OctopError(ErrorCode.SHARE_STALE, "Preview changed; review a fresh preview")
        snapshot = {key: preview[key] for key in ("title", "timezone", "messages")}

        def save() -> dict[str, Any]:
            source = self.thread(owner, thread_id, agent_id)
            token = secrets.token_urlsafe(32)
            key = self.repos.secret_repo.get_or_create("thread_shares_fernet", Fernet.generate_key)
            now = time.time()
            value = self.repos.thread_share_repo.create(
                {
                    "share_id": new_ulid(),
                    "owner_user_id": owner,
                    "source_agent_id": source.agent_id,
                    "source_thread_id": thread_id,
                    "token_hash": hashlib.sha256(token.encode()).hexdigest(),
                    "encrypted_token": Fernet(key).encrypt(token.encode()).decode(),
                    "snapshot_json": canonical(snapshot),
                    "snapshot_version": 1,
                    "message_count": preview["message_count"],
                    "created_at": now,
                    "expires_at": now + expires_in_seconds
                    if expires_in_seconds is not None
                    else None,
                    "revoked_at": None,
                }
            )
            return self.record(value)

        return await asyncio.to_thread(save)

    def record(self, row: dict[str, Any]) -> dict[str, Any]:
        snapshot = json.loads(row["snapshot_json"])
        status = (
            "revoked"
            if row["revoked_at"] is not None
            else "expired"
            if row["expires_at"] is not None and row["expires_at"] <= time.time()
            else "active"
        )
        path = url = None
        if status == "active" and row["encrypted_token"]:
            key = self.repos.secret_repo.get("thread_shares_fernet")
            if key is not None:
                token = Fernet(key).decrypt(row["encrypted_token"].encode()).decode()
                path = "/share/" + token
                origin = validate_public_origin(self.config.public_origin)
                url = origin + path if origin else None
        return {
            "share_id": row["share_id"],
            "public_url": url,
            "public_path": path,
            "title": snapshot["title"],
            "agent_id": row["source_agent_id"],
            "thread_id": row["source_thread_id"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "revoked_at": row["revoked_at"],
            "status": status,
            "message_count": row["message_count"],
        }

    def list(
        self,
        owner: int,
        *,
        thread_id: str | None = None,
        agent_id: str | None = None,
        before: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        self.owner(owner)
        if thread_id is not None:
            self.thread(owner, thread_id, agent_id)
        if before is not None and (
            not re.fullmatch(r"[1-9][0-9]{0,18}", before) or int(before) > 2**63 - 1
        ):
            raise OctopError(ErrorCode.SHARE_INVALID, "Invalid share cursor")
        size = max(1, min(limit, 100))
        rows = self.repos.thread_share_repo.list(
            owner, thread_id=thread_id, before=int(before) if before else None, limit=size + 1
        )
        selected = rows[:size]
        more = len(rows) > size
        return {
            "shares": [self.record(row) for row in selected],
            "has_more": more,
            "next_before": str(selected[-1]["id"]) if more else None,
        }

    def revoke(self, owner: int, share_id: str) -> None:
        self.owner(owner)
        if not self.repos.thread_share_repo.revoke(owner, share_id, time.time()):
            raise OctopError(ErrorCode.NOT_FOUND, "Share unavailable")

    def public(self, token: str) -> dict[str, Any]:
        if not TOKEN_PATTERN.fullmatch(token):
            raise OctopError(ErrorCode.NOT_FOUND, "Share unavailable")
        row = self.repos.thread_share_repo.public(
            hashlib.sha256(token.encode()).hexdigest(), time.time()
        )
        if row is None:
            raise OctopError(ErrorCode.NOT_FOUND, "Share unavailable")
        return {
            **json.loads(row["snapshot_json"]),
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
        }
