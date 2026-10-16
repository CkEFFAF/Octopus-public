"""Workspace-backed subagent definitions shared by HTTP and native tools."""

from __future__ import annotations

import asyncio
import json
import re
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.frontmatter import parse_frontmatter


@dataclass
class _DefinitionLock:
    lock: asyncio.Lock
    users: int = 0


_WRITE_LOCKS: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[tuple[str, str], _DefinitionLock]
] = weakref.WeakKeyDictionary()


@asynccontextmanager
async def _definition_lock(agent_id: str, path: str) -> AsyncIterator[None]:
    """Share one lock per definition across transports; release idle keys and loops."""
    loop = asyncio.get_running_loop()
    locks = _WRITE_LOCKS.setdefault(loop, {})
    key = (agent_id, path)
    entry = locks.setdefault(key, _DefinitionLock(asyncio.Lock()))
    entry.users += 1
    try:
        async with entry.lock:
            yield
    finally:
        entry.users -= 1
        if not entry.users:
            locks.pop(key, None)
        if not locks:
            _WRITE_LOCKS.pop(loop, None)


def subagent_path(slug: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", slug):
        raise ValueError("slug must contain 1–80 lowercase letters, digits, _ or -")
    return f"agents/{slug}.md"


async def write_definition(
    workspace: Any, slug: str, content: str, *, agent_id: str, replace: bool
) -> str:
    """Validate before writing; callers own authorization and reload scheduling."""
    path = subagent_path(slug)
    meta, body = parse_frontmatter(content)
    if (
        not isinstance(meta.get("name"), str)
        or not meta["name"].strip()
        or not isinstance(meta.get("description"), str)
        or not body.strip()
        or len(content) > 50_000
    ):
        raise ValueError("subagent needs name/description frontmatter and nonempty instructions")
    async with _definition_lock(agent_id, path):
        existing = await workspace.aread_text(path, limit=60_000)
        if replace and existing is None:
            raise OctopError(ErrorCode.NOT_FOUND, "subagent does not exist; create it first")
        if not replace and existing is not None:
            raise ValueError("subagent already exists; explicitly replace it")
        await workspace.aupload_bytes(path, content.encode("utf-8"))
    return path


def custom_definition(name: str, description: str, instructions: str) -> str:
    if not 1 <= len(name.strip()) <= 80 or len(description) > 500:
        raise ValueError("name must be 1–80 characters; description at most 500")
    # JSON scalar quoting is valid YAML and cannot inject extra frontmatter fields.
    return (
        f"---\nname: {json.dumps(name.strip(), ensure_ascii=False)}\n"
        f"description: {json.dumps(description, ensure_ascii=False)}\n---\n\n{instructions}"
    )


def catalog_content(item: Any, requested: str) -> tuple[str, str]:
    available = item.summary.available_locales
    installed = requested if requested in available or "en" not in available else "en"
    return item.content_for(installed), installed
