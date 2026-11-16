"""One-shot calls share the same conversation write lock as streaming."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from octop.infra.agents.manager import AgentManager


@asynccontextmanager
async def _invocation(_agent_id: str) -> AsyncIterator[None]:
    yield


def _manager(call: Any) -> AgentManager:
    manager = AgentManager.__new__(AgentManager)
    manager._thread_execution_locks = {}
    manager._harness_manager = SimpleNamespace(call=call)  # type: ignore[assignment]
    manager._track_invocation = _invocation  # type: ignore[method-assign]
    manager._apply_pending_bootstrap_graph_refresh = Mock()  # type: ignore[method-assign]
    manager._prepare_stream_request = lambda _aid, request: request  # type: ignore[method-assign]
    manager._route_stream_request = lambda _aid, request: request  # type: ignore[method-assign]
    return manager


@pytest.mark.asyncio
async def test_call_waits_for_existing_conversation_writer() -> None:
    underlying = AsyncMock(return_value={"answer": "done"})
    manager = _manager(underlying)
    request = {"thread_id": "thread"}
    async with manager._thread_execution_lock("agent", "thread"):
        pending = asyncio.create_task(manager.call("agent", request))
        try:
            await asyncio.sleep(0)
            underlying.assert_not_awaited()
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    assert await manager.call("agent", request) == {"answer": "done"}


@pytest.mark.asyncio
@pytest.mark.parametrize("same_thread", [True, False])
async def test_call_serializes_only_the_same_conversation(same_thread: bool) -> None:
    first_started, release_first, second_started = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def underlying(_aid: str, request: dict[str, Any]) -> dict[str, Any]:
        if request["tag"] == "first":
            first_started.set()
            await release_first.wait()
        else:
            second_started.set()
        return {}

    manager = _manager(underlying)
    first = asyncio.create_task(manager.call("agent", {"thread_id": "A", "tag": "first"}))
    await asyncio.wait_for(first_started.wait(), 1)
    second = asyncio.create_task(
        manager.call("agent", {"thread_id": "A" if same_thread else "B", "tag": "second"})
    )
    try:
        if same_thread:
            await asyncio.sleep(0)
            assert not second_started.is_set()
        else:
            await asyncio.wait_for(second_started.wait(), 1)
    finally:
        release_first.set()
        await asyncio.gather(first, second)
    assert second_started.is_set()


@pytest.mark.asyncio
async def test_cancelled_call_releases_conversation_lock() -> None:
    started = asyncio.Event()

    async def underlying(*_args: Any) -> dict[str, Any]:
        started.set()
        await asyncio.Event().wait()
        return {}

    manager = _manager(underlying)
    task = asyncio.create_task(manager.call("agent", {"thread_id": "A"}))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not manager._thread_execution_lock("agent", "A").locked()
