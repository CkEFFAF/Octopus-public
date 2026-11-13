"""Composer context for dashboard chat turns."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from octop.api.routers.chat.turn import resolve_thread_id
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.gateway.process.message_keys import build_composer_context


class _ThreadRegistry:
    def __init__(self, row: object) -> None:
        self.row = row
        self.rebound = False

    def get_session(self, session_key: str) -> None:
        return None

    def get_thread(self, thread_id: str) -> object:
        assert thread_id == "owner-thread"
        return self.row

    async def rebind(self, **_kwargs: object) -> None:
        self.rebound = True


async def test_resolve_thread_id_rejects_another_users_thread() -> None:
    registry = _ThreadRegistry(SimpleNamespace(agent_id="shared-agent", user_id=1))

    with pytest.raises(OctopError) as exc_info:
        await resolve_thread_id(
            agent_id="shared-agent",
            user_id=2,
            thread_registry=registry,
            thread_id="owner-thread",
            session_key=None,
        )

    assert exc_info.value.code == ErrorCode.FORBIDDEN
    assert registry.rebound is False


@pytest.mark.parametrize("channel_type", ["dashboard", "cli"])
async def test_virtual_turn_rejects_foreign_session_or_thread(channel_type):
    from unittest.mock import AsyncMock, Mock

    from octop.infra.gateway.cli.turn import prepare_cli_turn

    resolver = resolve_thread_id if channel_type == "dashboard" else prepare_cli_turn
    registry = Mock()
    registry.rebind = AsyncMock()
    registry.get_session.return_value = SimpleNamespace(user_id=2, agent_id="agent")
    args = {
        "thread_registry": registry,
        "agent_id": "agent",
        "user_id": 1,
        "session_key": "session",
    }
    with pytest.raises(OctopError) as foreign_session:
        await resolver(**args, thread_id="own-thread")
    assert foreign_session.value.code == ErrorCode.FORBIDDEN
    registry.get_session.return_value = SimpleNamespace(user_id=1, agent_id="agent")
    registry.get_bound_thread_id.return_value = "another-thread"
    registry.get_thread.return_value = SimpleNamespace(user_id=2, agent_id="agent")
    for thread in (None, "another-thread"):
        with pytest.raises(OctopError) as foreign_thread:
            await resolver(**args, thread_id=thread)
        assert foreign_thread.value.code == ErrorCode.FORBIDDEN
    registry.rebind.assert_not_awaited()


def test_build_composer_context_omits_default_model() -> None:
    ctx = build_composer_context(
        mcp_servers=["github"],
        skills=["docx"],
        target_agent_ids=["agent-b"],
        model_ref="openai/gpt-4o",
        default_model="openai/gpt-4o",
    )
    assert ctx == {
        "connectors": ["github"],
        "skills": ["docx"],
        "targetAgents": ["agent-b"],
    }


def test_build_composer_context_includes_model_override() -> None:
    ctx = build_composer_context(
        mcp_servers=None,
        skills=None,
        target_agent_ids=None,
        model_ref="openai/gpt-4o-mini",
        default_model="openai/gpt-4o",
    )
    assert ctx == {"model": "openai/gpt-4o-mini"}
