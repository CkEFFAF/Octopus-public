"""Completed state and its streamed progress/final must not become two answers."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from octop.infra.history.projection import TurnHistoryTracker, _wire_text


def test_progress_tool_and_final_keep_authoritative_messages_without_aggregate_copy():
    user = HumanMessage(content="read the paper", id="user")
    progress = AIMessage(content="I will read it.", id="progress")
    result = ToolMessage(content="paper text", tool_call_id="read", id="result")
    final = AIMessage(content="The paper describes a graph model.", id="final")
    tracker = TurnHistoryTracker(seed_messages=[user])
    for text in (progress.content, final.content):
        tracker.observe({"type": "token", "content": text})
    tracker.observe({"type": "state_update", "data": {"messages": [user, progress, result, final]}})
    assert [(item.message_id, _wire_text(item)) for item in tracker.inputs] == [
        ("user", user.content),
        ("progress", progress.content),
        ("result", result.content),
        ("final", final.content),
    ]


def test_unpersisted_partial_tail_survives_after_a_persisted_progress_message():
    user = HumanMessage(content="read paper", id="user")
    tracker = TurnHistoryTracker(seed_messages=[user])
    tracker.observe({"type": "token", "content": "Reading."})
    tracker.observe(
        {
            "type": "state_update",
            "data": {"messages": [user, AIMessage(content="Reading.", id="p")]},
        }
    )
    tracker.observe({"type": "token", "content": "Partial answer"})
    assert [_wire_text(item) for item in tracker.inputs] == [
        "read paper",
        "Reading.",
        "Partial answer",
    ]


def test_completed_state_keeps_repeated_messages_by_identity_and_no_aggregate():
    tracker = TurnHistoryTracker(seed_messages=[HumanMessage(content="repeat", id="u")])
    tracker.observe({"type": "token", "content": "SameSame"})
    tracker.observe(
        {
            "type": "state_update",
            "data": {
                "messages": [
                    HumanMessage(content="repeat", id="u"),
                    AIMessage(content="Same", id="a"),
                    AIMessage(content="Same", id="b"),
                ]
            },
        }
    )
    tracker.observe({"type": "done"})
    assert [(item.message_id, _wire_text(item)) for item in tracker.inputs] == [
        ("u", "repeat"),
        ("a", "Same"),
        ("b", "Same"),
    ]


def test_interrupted_stream_is_marked_partial():
    import json

    tracker = TurnHistoryTracker(seed_messages=[HumanMessage(content="q", id="u")])
    tracker.observe({"type": "token", "content": "partial"})
    partial = tracker.inputs[-1]
    assert json.loads(partial.message_json)["data"]["additional_kwargs"]["octop_partial"] is True
