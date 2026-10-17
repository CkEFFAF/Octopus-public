"""Capacity provenance must survive restart, thread model selection and 128k caps."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from octop.infra.agents.manager import AgentManager


@pytest.mark.parametrize(
    ("override", "thread_model", "expected"),
    [
        (None, "p/large", (1_000_000, "model")),
        (128_000, "p/large", (128_000, "agent_config")),
        (500_000, "p/small", (128_000, "agent_config")),
        (None, "p/unknown", (None, "compatibility_default")),
        (None, None, (1_000_000, "model")),
    ],
)
@pytest.mark.parametrize("thread_owner", [1, 2])
def test_effective_capacity(override, thread_model, expected, thread_owner):
    manager = MagicMock(spec=AgentManager)
    manager.get_row.return_value = SimpleNamespace(user_id=1)
    manager.get_config.return_value = {"max_input_length": override}
    manager._repos = SimpleNamespace(
        thread_repo=SimpleNamespace(
            get=lambda _: SimpleNamespace(
                agent_id="gpu", user_id=thread_owner, model_ref=thread_model
            )
        )
    )
    manager.get_thread_model.return_value = None
    store = manager.providers_for_agent.return_value
    store.is_model_ref_usable.return_value = True
    store.resolve_explicit_default_model.return_value = "p/large"
    store.iter_usable_rows.return_value = [
        SimpleNamespace(
            name="p",
            get_models=lambda: [
                {"id": "large", "context_window": 1_000_000},
                {"id": "small", "context_window": 128_000},
                {"id": "unknown"},
            ],
        )
    ]
    assert AgentManager.resolve_context_capacity(manager, "gpu", "thread") == expected


def test_foreign_thread_capacity_is_denied():
    manager = MagicMock(spec=AgentManager)
    manager.get_row.return_value = SimpleNamespace(user_id=1)
    manager._repos = SimpleNamespace(
        thread_repo=SimpleNamespace(get=lambda _: SimpleNamespace(agent_id="other", user_id=2))
    )
    with pytest.raises(ValueError, match="conversation unavailable"):
        AgentManager.resolve_context_capacity(manager, "gpu", "foreign")
