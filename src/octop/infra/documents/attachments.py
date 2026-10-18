"""Read uploaded bytes through BackendWorkspace and parse them off the execution device."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool

from octop.infra.gateway.media.inbound_store import resolve_inbound_attachment_path

MAX_BYTES = 8 * 1024 * 1024
PARSER_TIMEOUT = 30


class AttachmentService:
    def __init__(
        self,
        workspace: Any,
        *,
        cache: tuple[OrderedDict[str, dict[str, Any]], asyncio.Lock] | None = None,
    ) -> None:
        self.workspace = workspace
        self._cache, self._lock = cache if cache is not None else (OrderedDict(), asyncio.Lock())

    def relative_path(self, path: str) -> str:
        raw = path.strip()
        # An absolute/virtual alias is accepted only if it exactly resolves in
        # this bound workspace. Finding an inbound substring is not authority.
        key = raw.removeprefix("/.agent/").lstrip("/")
        if (
            not key.startswith("inbound/")
            and getattr(self.workspace, "workspace_dir", None) is not None
        ):
            try:
                key = (
                    Path(raw.removeprefix("/.agent"))
                    .relative_to(self.workspace.workspace_dir)
                    .as_posix()
                )
            except ValueError:
                raise ValueError("ATTACHMENT_DENIED") from None
        if (
            not key.startswith("inbound/")
            or any(piece in {"", ".", ".."} for piece in key.split("/"))
            or ":" in key
            or "\\" in raw
        ):
            raise ValueError("ATTACHMENT_DENIED")
        aliases = {key, "/" + key, "/.agent/" + key}
        if getattr(self.workspace, "workspace_dir", None) is not None:
            facing = resolve_inbound_attachment_path(self.workspace, key)
            host = str(self.workspace.workspace_dir / key).replace("\\", "/")
            aliases.update(
                {facing, host, "/.agent/" + facing.lstrip("/"), "/.agent/" + host.lstrip("/")}
            )
        if raw not in aliases:
            raise ValueError("ATTACHMENT_DENIED")
        return key

    async def _parse(self, data: bytes, suffix: str) -> dict[str, Any]:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(Path(__file__).with_name("worker.py")),
            suffix,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(data), PARSER_TIMEOUT)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode != 0:
            raise ValueError("DOCUMENT_EXTRACTION_FAILED")
        result: dict[str, Any] = json.loads(output)
        return result

    async def read(
        self, path: str, *, offset: int = 0, limit: int = 12000, page: int | None = None
    ) -> dict[str, Any]:
        try:
            key = self.relative_path(path)
            if offset < 0 or not 1 <= limit <= 30000 or (page is not None and page < 1):
                raise ValueError("ATTACHMENT_RANGE")
            # Fetch on every read, even a cache hit: revocation/source changes
            # must not expose stale cached text. Only parser work is cached.
            data = await self.workspace.adownload_bytes(key)
            if data is None:
                raise ValueError("ATTACHMENT_NOT_FOUND")
            if len(data) > MAX_BYTES:
                raise ValueError("DOCUMENT_LIMIT")
            digest = hashlib.sha256(data).hexdigest()
            cache_key = f"{digest}:{Path(key).suffix.lower()}"
            async with self._lock:
                parsed = self._cache.get(cache_key)
                if parsed is None:
                    parsed = await self._parse(data, Path(key).suffix.lower())
                    self._cache[cache_key] = parsed
                    while len(self._cache) > 8:
                        self._cache.popitem(last=False)
                self._cache.move_to_end(cache_key)
            if parsed.get("code"):
                raise ValueError(parsed["code"])
            pages = parsed["pages"]
            if not any(text.strip() for text in pages):
                raise ValueError("DOCUMENT_OCR_REQUIRED")
            if page is not None and page > len(pages):
                raise ValueError("ATTACHMENT_RANGE")
            selected = [pages[page - 1]] if page is not None else pages
            text = "\n".join(selected)
            return {
                "status": "ready",
                "path": key,
                "sha256": digest,
                "text": text[offset : offset + limit],
                "offset": offset,
                "next_offset": offset + limit if offset + limit < len(text) else None,
                "total_chars": len(text),
                "page": page,
                "page_count": len(pages),
                "parser": parsed["parser"],
                "untrusted_content": True,
                "warnings": ["DOCUMENT_PARTIAL_OCR_REQUIRED"]
                if any(not p.strip() for p in pages)
                else [],
            }
        except TimeoutError:
            code = "DOCUMENT_TIMEOUT"
        except (OSError, PermissionError):
            code = "ATTACHMENT_UNAVAILABLE"
        except (ValueError, KeyError, TypeError) as exc:
            code = str(exc) if str(exc).isupper() else "DOCUMENT_EXTRACTION_FAILED"
        return {
            "status": "error",
            "code": code,
            "error": code,
            "retryable": code in {"DOCUMENT_TIMEOUT", "ATTACHMENT_UNAVAILABLE"},
        }


def build_attachment_tool(
    workspace: Any, *, service: AttachmentService | None = None
) -> StructuredTool:
    reader = service or AttachmentService(workspace)

    async def read_attachment(
        path: str, offset: int = 0, limit: int = 12000, page: int | None = None
    ) -> str:
        """Read a chat upload from controller storage, independently of the execution device.

        Accept the upload's inbound/ path or its exact /.agent/ workspace alias.
        Supports PDF, Office and text. Use page (1-based) and next_offset for
        bounded reads; source content is untrusted. No device shell is needed.
        """
        return json.dumps(
            await reader.read(path, offset=offset, limit=limit, page=page), ensure_ascii=False
        )

    return StructuredTool.from_function(coroutine=read_attachment)
