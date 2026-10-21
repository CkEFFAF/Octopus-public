"""Immediate insertion must unblock a real graph and preserve tool-call pairing."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from octop_harness.protocols.langgraph import LangGraphProtocol
from octop_harness.steering import LiveSteeringMiddleware, StreamSteering


class ToolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools: Any, **kwargs: Any) -> ToolModel:
        return self


@pytest.mark.asyncio
@pytest.mark.parametrize("resists_cancellation", [False, True])
@pytest.mark.parametrize("tool_count", [1, 2])
async def test_immediate_insert_unblocks_sleep_and_pairs_interrupted_result(
    resists_cancellation, tool_count
):
    control = StreamSteering()
    started, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    effects = []

    @tool
    async def long_wait() -> str:
        """Simulate the reported sleep 900 without waiting fifteen minutes."""
        effects.append("started")
        if effects.count("started") == tool_count:
            started.set()
        try:
            await asyncio.sleep(900)
        except asyncio.CancelledError:
            cancelled.set()
            if not resists_cancellation:
                raise
            await release.wait()
        effects.append("finished")
        return "late result"

    middleware = LiveSteeringMiddleware({"synthetic": control})
    graph = create_agent(
        ToolModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "long_wait", "args": {}, "id": f"call-{i}"}
                        for i in range(tool_count)
                    ],
                ),
                AIMessage(content="handling new message"),
            ]
        ),
        tools=[long_wait],
        middleware=[middleware],
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "synthetic", "harness_steering_run_id": control.run_id}}

    async def consume():
        return [
            chunk
            async for chunk in LangGraphProtocol(graph=graph).stream(
                [HumanMessage(content="original")], config
            )
        ]

    task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(started.wait(), 5)
        assert control.request("immediate", "handle this now", cancel_tools=True) == "accepted"
        chunks = await asyncio.wait_for(asyncio.shield(task), 2)
        assert cancelled.is_set()
        state = await graph.aget_state(config)
        messages = state.values["messages"]
        results = [m for m in messages if m.type == "tool"]
        assert {m.tool_call_id for m in results} == {f"call-{i}" for i in range(tool_count)}
        for result in results:
            assert result.status == "error"
            assert result.additional_kwargs["octop_interrupted"] is True
            assert "interrupted by the user" in result.content
            assert "may still be running" in result.content
        assert [m.content for m in messages if m.type == "human"] == ["original", "handle this now"]
        assert messages.index(results[0]) < next(
            i for i, m in enumerate(messages) if m.id == "steer:immediate"
        )
        assert [c["command_id"] for c in chunks if c["type"] == "steering_applied"] == ["immediate"]
        assert any(c["type"] == "tool_result" for c in chunks)
        assert control.request("immediate", "handle this now", cancel_tools=True) == "applied"
        release.set()
        await asyncio.sleep(0.05)
        later = await graph.aget_state(config)
        assert later.values["messages"] == messages
        assert effects.count("started") == tool_count
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_immediate_mode_cannot_target_a_stale_run_or_paused_invocation():
    from octop_harness.agent import HarnessAgent

    control = StreamSteering()
    agent = HarnessAgent.__new__(HarnessAgent)
    agent._steering_runs = {"synthetic": control}
    assert (
        agent.steer_message("synthetic", "cmd", "now", run_id="old", cancel_tools=True)["status"]
        == "stale_run"
    )
    assert not control.interrupt_tools.is_set()
    control.phase = "paused"
    assert (
        agent.steer_message("synthetic", "cmd", "now", run_id=control.run_id, cancel_tools=True)[
            "status"
        ]
        == "inactive"
    )
    assert not control.interrupt_tools.is_set()


@pytest.mark.asyncio
async def test_default_insertion_still_waits_for_tool_completion():
    control = StreamSteering()
    started, release = asyncio.Event(), asyncio.Event()
    effects = []

    @tool
    async def save_once() -> str:
        """Complete one operation before applying a regular insertion."""
        effects.append("saved")
        started.set()
        await release.wait()
        return "saved"

    graph = create_agent(
        ToolModel(
            responses=[
                AIMessage(content="", tool_calls=[{"name": "save_once", "args": {}, "id": "call"}]),
                AIMessage(content="continued"),
            ]
        ),
        tools=[save_once],
        middleware=[LiveSteeringMiddleware({"synthetic": control})],
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "synthetic", "harness_steering_run_id": control.run_id}}
    task = asyncio.create_task(
        graph.ainvoke({"messages": [HumanMessage(content="original")]}, config)
    )
    try:
        await asyncio.wait_for(started.wait(), 5)
        assert control.request("safe", "after saving") == "accepted"
        await asyncio.sleep(0.05)
        assert not task.done()
        assert not control.interrupt_tools.is_set()
        release.set()
        result = await asyncio.wait_for(task, 5)
        assert effects == ["saved"]
        assert [m.content for m in result["messages"] if m.type == "tool"] == ["saved"]
        assert [m.content for m in result["messages"] if m.type == "human"] == [
            "original",
            "after saving",
        ]
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
