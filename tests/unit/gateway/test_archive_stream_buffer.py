from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from octop.infra.history.stream_buffer import archive_stream


async def test_ready_text_batches_preserve_every_fragment_and_speaker_boundary():
    frames = [
        *({"type": "token", "content": str(i), "agent_id": "a"} for i in range(300)),
        {"type": "token", "content": "other", "agent_id": "b"},
        {"type": "done"},
    ]

    async def source():
        for frame in frames:
            yield frame

    tracker = SimpleNamespace(turn={"format": "v2"})
    result = [chunk async for chunk in archive_stream(source(), tracker)]
    assert result[0] == frames[0]
    assert "".join(row["content"] for row in result if row.get("agent_id") == "a") == "".join(
        str(i) for i in range(300)
    )
    assert result[-2:] == frames[-2:]
    assert len(result) < 10


async def test_control_event_blocks_read_ahead_and_close_cleans_up_producer():
    advanced = asyncio.Event()
    closed = asyncio.Event()

    async def source():
        try:
            yield {"type": "hitl_required", "request": {}}
            advanced.set()
            yield {"type": "token", "content": "after approval"}
        finally:
            closed.set()

    stream = archive_stream(source(), SimpleNamespace(turn={"format": "v2"}))
    assert (await anext(stream))["type"] == "hitl_required"
    await asyncio.sleep(0)
    assert not advanced.is_set()
    await stream.aclose()
    assert closed.is_set()


async def test_stream_exception_is_delivered_after_preceding_text():
    async def source():
        yield {"type": "token", "content": "committed first"}
        yield {"type": "token", "content": "second"}
        raise OSError("provider unavailable")

    stream = archive_stream(source(), SimpleNamespace(turn={"format": "v2"}))
    assert (await anext(stream))["content"] == "committed first"
    assert (await anext(stream))["content"] == "second"
    with pytest.raises(OSError, match="provider unavailable"):
        await anext(stream)


async def test_legacy_stream_is_not_prefetched_or_coalesced():
    seen = []

    async def source():
        for i in range(3):
            seen.append(i)
            yield {"type": "token", "content": str(i)}

    stream = archive_stream(source(), None)
    assert (await anext(stream))["content"] == "0"
    assert seen == [0]
    assert [item["content"] async for item in stream] == ["1", "2"]


async def test_cancelled_source_wakes_consumer_after_queued_text():
    async def source():
        yield {"type": "token", "content": "before cancellation"}
        raise asyncio.CancelledError()

    stream = archive_stream(source(), SimpleNamespace(turn={"format": "v2"}))
    assert (await anext(stream))["content"] == "before cancellation"
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(anext(stream), 5)


async def test_close_cancels_a_producer_with_a_full_queue():
    closed = asyncio.Event()

    async def source():
        try:
            for _ in range(1000):
                yield {"type": "token", "content": "text"}
        finally:
            closed.set()

    stream = archive_stream(source(), SimpleNamespace(turn={"format": "v2"}))
    await anext(stream)
    await asyncio.sleep(0)
    await asyncio.wait_for(stream.aclose(), 5)
    assert closed.is_set()


async def test_external_producer_cancellation_finishes_with_a_full_queue():
    saturated = asyncio.Event()
    closed = asyncio.Event()

    async def source():
        try:
            for i in range(1000):
                if i == 65:
                    saturated.set()
                yield {"type": "token", "content": "text"}
        finally:
            closed.set()

    before = asyncio.all_tasks()
    stream = archive_stream(source(), SimpleNamespace(turn={"format": "v2"}))
    await anext(stream)
    try:
        await asyncio.wait_for(saturated.wait(), 5)
        producer = next(
            task
            for task in asyncio.all_tasks() - before
            if task.get_name() == "history-stream-buffer"
        )
        producer.cancel()
        done, _ = await asyncio.wait({producer}, timeout=1)
        assert producer in done
        assert closed.is_set()
        assert (await anext(stream))["content"]
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(anext(stream), 5)
    finally:
        await stream.aclose()
