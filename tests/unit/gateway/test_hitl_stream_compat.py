"""LangGraph v2 interrupt projection for dashboard HITL."""

from __future__ import annotations

from octop.infra.gateway.hitl.stream_compat import (
    hitl_events_from_interrupts,
    merge_hitl_projection,
)


def test_hitl_events_from_interrupt_objects() -> None:
    class _Interrupt:
        def __init__(self, value: object) -> None:
            self.value = value

    events = hitl_events_from_interrupts(
        (
            _Interrupt(
                {
                    "action_requests": [
                        {
                            "name": "ask_user_question",
                            "args": {"questions": [{"question": "Go?"}]},
                        }
                    ]
                }
            ),
        )
    )
    assert len(events) == 1
    assert events[0]["type"] == "hitl_required"
    assert events[0]["request"]["action_requests"][0]["name"] == "ask_user_question"


def test_hitl_events_from_interrupt_dicts() -> None:
    events = hitl_events_from_interrupts(
        [
            {
                "id": "abc",
                "value": {
                    "action_requests": [{"name": "execute", "args": {"command": "ls"}}],
                },
            }
        ]
    )
    assert events[0]["request"]["action_requests"][0]["args"]["command"] == "ls"


def test_hitl_events_ignore_empty_envelopes() -> None:
    assert hitl_events_from_interrupts([{"id": "x", "value": {"raw": "nope"}}]) == []
    assert hitl_events_from_interrupts(None) == []


def test_merge_replaces_empty_hitl_required_from_interrupts() -> None:
    events = merge_hitl_projection(
        [{"type": "hitl_required", "request": {"id": "int-1", "value": {}}}],
        [
            {
                "id": "int-1",
                "value": {
                    "action_requests": [
                        {"name": "ask_user_question", "args": {"questions": [{"question": "Go?"}]}}
                    ]
                },
            }
        ],
    )
    assert len(events) == 1
    assert events[0]["request"]["action_requests"][0]["name"] == "ask_user_question"


def test_merge_keeps_actionable_hitl_required() -> None:
    existing = {
        "type": "hitl_required",
        "request": {"action_requests": [{"name": "execute", "args": {"command": "ls"}}]},
    }
    events = merge_hitl_projection(
        [existing],
        [{"value": {"action_requests": [{"name": "ask_user_question", "args": {}}]}}],
    )
    assert events == [existing]


def test_installed_projection_preserves_peer_isolation_and_interrupts(monkeypatch):
    from langchain_core.messages import AIMessageChunk
    from octop_harness.protocols.langgraph import LangGraphProtocol
    from octop_harness.protocols.think_splitter import ThinkSplitter

    from octop.infra.gateway.hitl import stream_compat

    monkeypatch.setattr(stream_compat, "_INSTALLED", False)
    monkeypatch.setattr(LangGraphProtocol, "_project_chunk", LangGraphProtocol._project_chunk)
    stream_compat.install_harness_hitl_compat()
    protocol = LangGraphProtocol(graph=None)
    chunk = {
        "type": "messages",
        "data": (
            AIMessageChunk(content="CHILD"),
            {"langgraph_node": "model", "harness_invocation_id": "child"},
        ),
        "interrupts": [{"value": {"action_requests": [{"name": "execute", "args": {}}]}}],
    }
    events = protocol._project_chunk(chunk, ThinkSplitter(), "parent")
    assert len(events) == 1 and events[0]["type"] == "hitl_required"
    chunk["data"] = (
        AIMessageChunk(content="HOST"),
        {"langgraph_node": "model", "harness_invocation_id": "parent"},
    )
    assert protocol._project_chunk(chunk, ThinkSplitter(), "parent")[0]["content"] == "HOST"
