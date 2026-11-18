"""Read both formats without creating or repairing legacy records."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from octop.infra.db.repos.thread_messages import ThreadMessageRepo
from octop.infra.history.legacy import checkpoint_snapshot, checkpoint_wires
from octop.infra.history.service import HistoryArchive


def legacy_history_cursor(
    thread_id: str,
    source: str,
    before: int,
    checkpoint_id: str | None = None,
) -> str:
    value: dict[str, Any] = {"thread": thread_id, "source": source, "before": before}
    if checkpoint_id is not None:
        value["checkpoint_id"] = checkpoint_id
    return "legacy:" + base64.urlsafe_b64encode(json.dumps(value).encode()).decode()


def decode_legacy_history_cursor(cursor: str, thread_id: str) -> dict[str, Any]:
    try:
        if not cursor.startswith("legacy:"):
            raise ValueError("Invalid legacy cursor prefix")
        boundary = json.loads(base64.urlsafe_b64decode(cursor[7:]))
        if (
            not isinstance(boundary, dict)
            or boundary.get("thread") != thread_id
            or type(boundary.get("before")) is not int
            or not 0 <= boundary["before"] < 2**63
            or boundary.get("source") not in ("projection", "checkpoint")
        ):
            raise ValueError("Invalid legacy cursor boundary")
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid legacy cursor") from exc
    return boundary


async def read_page(
    archive: HistoryArchive | None,
    registry: Any,
    agent_id: str,
    thread_id: str,
    *,
    limit: int,
    offset: int = 0,
    cursor: str | None = None,
    messages: ThreadMessageRepo | None = None,
    include_message_cursors: bool = False,
) -> dict[str, Any]:
    message_repo = archive.messages if archive is not None else messages
    if message_repo is None:
        raise ValueError("History message repository is unavailable")

    async def legacy(anchor: dict[str, Any]) -> list[Any]:
        return await checkpoint_wires(registry.get_agent(agent_id), thread_id, anchor)

    boundary = (
        decode_legacy_history_cursor(cursor, thread_id)
        if cursor and cursor.startswith("legacy:")
        else None
    )
    segments = await asyncio.to_thread(archive.store.segments, thread_id) if archive else []
    if boundary is None and segments and archive is not None:
        return await archive.page(
            thread_id,
            limit=limit,
            cursor=cursor,
            offset=offset,
            legacy_reader=legacy,
            include_message_cursors=include_message_cursors,
        )
    if cursor and boundary is None:
        raise ValueError("History cursor has no corresponding segment")
    source = (
        boundary["source"]
        if boundary
        else (
            "projection"
            if await asyncio.to_thread(message_repo.projection_status, thread_id) == "ready"
            else "checkpoint"
        )
    )
    anchor = None
    checkpoint_id = None
    if source == "projection":
        if boundary:
            descending = await asyncio.to_thread(
                message_repo.range_page, thread_id, 0, boundary["before"] - 1, limit + 1
            )
            rows, has_more = list(reversed(descending[:limit])), len(descending) > limit
        else:
            rows, has_more = await asyncio.to_thread(
                message_repo.page, thread_id, limit=limit, offset=offset
            )
        wires = [json.loads(row.message_json) for row in rows]
        before = rows[0].seq if rows else 0
        positions = [row.seq for row in rows] if include_message_cursors else []
    else:
        if boundary:
            # Never trust a cursor to select a different thread's checkpoint.
            checkpoint_id = boundary.get("checkpoint_id")
            if not isinstance(checkpoint_id, str) or not checkpoint_id:
                raise ValueError("Invalid pinned checkpoint")
            anchor = {
                "checkpoint_config": {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_id": checkpoint_id,
                        "checkpoint_ns": "",
                    }
                }
            }
        raw, config = await checkpoint_snapshot(registry.get_agent(agent_id), thread_id, anchor)
        stop = min(len(raw), boundary["before"]) if boundary else max(0, len(raw) - offset)
        start = max(0, stop - limit)
        wires, has_more, before = raw[start:stop], start > 0, start
        checkpoint_id = (config or {}).get("configurable", {}).get("checkpoint_id")
        if has_more and not checkpoint_id:
            raise ValueError("Cannot pin the legacy history page")
        positions = list(range(start, stop)) if include_message_cursors else []
    page = {
        "messages": wires,
        "has_more": has_more,
        "next_cursor": legacy_history_cursor(thread_id, source, before, checkpoint_id)
        if has_more
        else None,
    }
    if include_message_cursors:
        page["message_cursors"] = [
            legacy_history_cursor(thread_id, source, position + 1, checkpoint_id)
            if source == "projection" or checkpoint_id
            else None
            for position in positions
        ]
    return page


async def export_messages(
    archive: HistoryArchive, registry: Any, agent_id: str, thread_id: str
) -> list[Any]:
    page = await read_page(archive, registry, agent_id, thread_id, limit=1000)
    messages = page["messages"]
    while page["has_more"]:
        page = await read_page(
            archive,
            registry,
            agent_id,
            thread_id,
            limit=1000,
            offset=len(messages),
            cursor=page["next_cursor"],
        )
        messages = [*page["messages"], *messages]
    return messages  # type: ignore[no-any-return]
