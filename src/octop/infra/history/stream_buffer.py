"""Coalesce already received text while an archive consumer commits its last batch."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

from octop.infra.history.projection import TurnHistoryTracker
from octop.infra.metrics import PERFORMANCE


def _text(chunk: dict[str, Any]) -> bool:
    return (
        chunk.get("type") in {"token", "reasoning"}
        and isinstance(chunk.get("content"), str)
        and not chunk.get("team_snapshot")
        and not chunk.get("event_id")
    )


async def archive_stream(
    chunks: AsyncIterator[dict[str, Any]], tracker: TurnHistoryTracker | None
) -> AsyncIterator[dict[str, Any]]:
    """Keep the first event immediate and every forwarded batch durable.

    There is no batching timer: only text already received during persistence
    can be combined. A control event stops read ahead until the consumer has
    processed it, so tools, approvals and terminal events remain barriers.
    """
    started = time.perf_counter()
    first_text = True

    def received(chunk: dict[str, Any]) -> None:
        nonlocal first_text
        if (
            first_text
            and chunk.get("type") in {"token", "reasoning"}
            and isinstance(chunk.get("content"), str)
            and chunk["content"]
        ):
            PERFORMANCE.observe("first_text", time.perf_counter() - started)
            first_text = False

    if getattr(tracker, "turn", {}).get("format") != "v2":
        async for chunk in chunks:
            received(chunk)
            yield chunk
        return
    queue: asyncio.Queue[tuple[dict[str, Any], asyncio.Event | None]] = asyncio.Queue(maxsize=64)
    available = asyncio.Event()
    terminal: BaseException | None = None
    finished = False

    async def receive() -> None:
        nonlocal terminal, finished
        try:
            async for chunk in chunks:
                received(chunk)
                barrier = None if _text(chunk) else asyncio.Event()
                await queue.put((chunk, barrier))
                available.set()
                if barrier is not None:
                    await barrier.wait()
        except BaseException as exc:
            terminal = exc
        finally:
            close = getattr(chunks, "aclose", None)
            if close is not None:
                try:
                    await close()
                except BaseException as exc:
                    if terminal is None:
                        terminal = exc
            # Completion must never wait for queue capacity: shutdown can cancel
            # the producer while the consumer is paused and the queue is full.
            finished = True
            available.set()

    producer = asyncio.create_task(receive(), name="history-stream-buffer")
    pending = None
    first = True
    try:
        while True:
            if pending is not None:
                item, barrier = pending
            elif not queue.empty():
                item, barrier = queue.get_nowait()
            elif finished:
                if terminal is not None:
                    raise terminal
                return
            else:
                available.clear()
                await available.wait()
                continue
            pending = None
            if not first and _text(item):
                identity = {key: value for key, value in item.items() if key != "content"}
                parts = [item["content"]]
                size = len(parts[0])
                while not queue.empty() and size < 8192:
                    following, gate = queue.get_nowait()
                    if not _text(following) or identity != {
                        key: value for key, value in following.items() if key != "content"
                    }:
                        pending = (following, gate)
                        break
                    parts.append(following["content"])
                    size += len(parts[-1])
                if len(parts) > 1:
                    item = {**item, "content": "".join(parts)}
            first = False
            yield item
            if barrier is not None:
                barrier.set()
    finally:
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)
