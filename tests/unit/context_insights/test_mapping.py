from octop.infra.context_insights.mapping import map_event_kind


def test_trajectory_kinds_map() -> None:
    assert map_event_kind("compacted") == "compact"
    assert map_event_kind("context") == "inject"
    assert map_event_kind("system") == "inject"
    assert map_event_kind("user") == "user"
    assert map_event_kind("assistant") == "assistant"
    assert map_event_kind("tool") == "tool"
    assert map_event_kind("mystery") == "other"


def test_transformation_payload_marks_compact() -> None:
    assert (
        map_event_kind(
            "assistant",
            payload={"transformation": {"kind": "summarization"}},
        )
        == "compact"
    )
    assert map_event_kind("assistant", payload={"prune": True}) == "prune"


def test_run_event_kinds_map() -> None:
    assert map_event_kind("model", source="run_event") == "model"
    assert map_event_kind("device", source="run_event") == "switch"
    assert map_event_kind("workflow", source="run_event") == "mode"
    assert map_event_kind("custom", source="run_event", payload={"work_mode": "ask"}) == "mode"
