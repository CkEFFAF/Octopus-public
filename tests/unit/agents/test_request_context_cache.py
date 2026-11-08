"""Final model requests keep historical context stable across tools and turns."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from octop.infra.agents.middleware.work_mode import WorkModeMiddleware
from octop.infra.conversations.middleware import ConversationBriefMiddleware


@pytest.mark.asyncio
async def test_context_replay_preserves_final_request_prefix_and_clean_checkpoint(monkeypatch):
    from langchain.agents import create_agent

    brief_reads = []
    workflow = {"payload": {"mode": "agentic", "version": 0}, "run_id": "run-one"}
    revision = [1]

    class Model(FakeMessagesListChatModel):
        seen: list[list[BaseMessage]] = Field(default_factory=list)

        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            self.seen.append(deepcopy(messages))
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    brief = ConversationBriefMiddleware(
        SimpleNamespace(_config=SimpleNamespace(default_timezone="UTC")), "expert"
    )

    def read_brief():
        brief_reads.append(revision[0])
        return f"\n[Derived conversation data]\nsource_revision={revision[0]}"

    monkeypatch.setattr(brief, "_context", read_brief)
    mode = WorkModeMiddleware(SimpleNamespace(begin=lambda *args: deepcopy(workflow)), "expert")

    @tool
    def update_progress() -> str:
        """Record a new real workflow result and refresh the derived summary."""
        revision[0] += 1
        workflow["payload"]["version"] += 1
        return "真实进度已更新"

    model = Model(
        responses=[
            AIMessage("", tool_calls=[{"id": "progress", "name": "update_progress", "args": {}}]),
            AIMessage("第一轮完成"),
            AIMessage("第二轮完成"),
        ]
    )
    checkpoint = InMemorySaver()
    graph = create_agent(
        model=model,
        tools=[update_progress],
        middleware=[brief, mode],
        checkpointer=checkpoint,
        system_prompt="Stable expert instructions",
    )
    config = {
        "configurable": {"thread_id": "cache-context", "user": 7, "octop_task_run_id": "run-one"}
    }
    first = await graph.ainvoke(
        {"messages": [HumanMessage("第一条原始问题", id="user-one")]}, config=config
    )
    assert len(model.seen) == 2
    systems = [
        next(m.content for m in messages if isinstance(m, SystemMessage)) for messages in model.seen
    ]
    assert systems[0] == systems[1]
    users = [
        next(m.content for m in messages if isinstance(m, HumanMessage)) for messages in model.seen
    ]
    assert users[0] == users[1]
    assert "source_revision=1" in str(users[0])
    assert brief_reads == [1]
    assert next(m for m in first["messages"] if m.id == "user-one").content == "第一条原始问题"

    workflow["run_id"] = "run-two"
    config["configurable"]["octop_task_run_id"] = "run-two"
    # A fresh compiled graph must replay the checkpoint without process-local caches.
    resumed = create_agent(
        model=model,
        tools=[update_progress],
        middleware=[brief, mode],
        checkpointer=checkpoint,
        system_prompt="Stable expert instructions",
    )
    await resumed.ainvoke(
        {"messages": [HumanMessage("第二条原始问题", id="user-two")]}, config=config
    )
    third = model.seen[2]
    assert next(m.content for m in third if isinstance(m, SystemMessage)) == systems[0]
    assert [m.content for m in third if isinstance(m, HumanMessage)][0] == users[0]
    assert "source_revision=2" in str([m for m in third if isinstance(m, HumanMessage)][-1].content)
    assert brief_reads == [1, 2]


def test_context_replay_composes_with_recall_and_invalidates_edited_content():
    from langchain.agents.middleware import ModelRequest
    from octop_harness.middleware.memory_recall import (
        replay_recall_snapshots,
        stamp_recall_snapshot,
    )

    from octop.infra.agents.middleware.request_context import capture_context, replay_context

    original = HumanMessage("Original user text", id="user", additional_kwargs={"other": "kept"})
    stamped = capture_context({"messages": [original]}, "_test_context", lambda: "\nDerived data")[
        "messages"
    ][0]
    recalled = stamp_recall_snapshot(stamped, "Saved memory")
    api = replay_recall_snapshots([recalled])
    request = ModelRequest(model=None, messages=api, state={"messages": [recalled]}, runtime=None)
    replayed = replay_context(request, "_test_context")
    assert "Saved memory" in replayed[0].content
    assert replayed[0].content.endswith("\nDerived data")
    assert "_test_context" not in replayed[0].additional_kwargs
    assert replayed[0].additional_kwargs["other"] == "kept"
    assert recalled.content == "Original user text"
    edited = recalled.model_copy(update={"content": "Edited user text"})
    request = ModelRequest(
        model=None, messages=[edited], state={"messages": [edited]}, runtime=None
    )
    assert replay_context(request, "_test_context")[0].content == "Edited user text"


def test_context_snapshot_does_not_introduce_late_data_or_mutate_image_blocks():
    from langchain.agents.middleware import ModelRequest

    from octop.infra.agents.middleware.request_context import capture_context, replay_context

    image = HumanMessage(
        [{"type": "image_url", "image_url": {"url": "https://example.invalid/test.png"}}],
        id="image",
    )
    stamped = capture_context({"messages": [image]}, "_test_context", lambda: "")["messages"][0]
    assert capture_context({"messages": [stamped]}, "_test_context", lambda: "Late data") is None
    request = ModelRequest(
        model=None, messages=[stamped], state={"messages": [stamped]}, runtime=None
    )
    copy = replay_context(request, "_test_context")[0]
    copy.content[0]["image_url"]["url"] = "changed by a downstream adapter"
    assert stamped.content[0]["image_url"]["url"] == "https://example.invalid/test.png"
