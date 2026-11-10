"""Keep importable workflow examples consistent with the executable schema."""

from pathlib import Path

import pytest

from octop.infra.workflow_graphs.models import GraphDefinition, validate_graph


@pytest.mark.parametrize("name", ["daily", "iteration", "event-start", "event-wait"])
def test_documented_definition_is_valid(name: str) -> None:
    root = Path(__file__).resolve().parents[3]
    definition = GraphDefinition.model_validate_json(
        (root / "docs" / "examples" / "workflow-graphs" / f"{name}.json").read_text(
            encoding="utf-8"
        )
    )
    assert validate_graph(definition) == []
    assert GraphDefinition.model_validate_json(definition.model_dump_json()) == definition
