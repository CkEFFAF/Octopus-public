"""0028 AC-I01: team host × (expert | default_open | device pack | explicit) → no MCP."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from octop_gateway.models import ChannelSubject, InboundMessage, TextContent

from octop.infra.gateway.process.processor import GlobalProcessor
from octop.infra.gateway.slash.dispatcher import SlashDispatcher
from octop.infra.isolation.team_host_mcp import (
    team_host_blocks_mcp,
    team_host_mcp_must_be_empty,
)


def _team_row() -> SimpleNamespace:
    return SimpleNamespace(kind="team", agent_id="host-1", mcp_servers='["evil-mcp"]')


def _expert_row() -> SimpleNamespace:
    return SimpleNamespace(kind="expert", agent_id="expert-1", mcp_servers='["docs__1"]')


def _processor(agent_manager: MagicMock) -> GlobalProcessor:
    return GlobalProcessor(
        agent_manager=agent_manager,
        thread_registry=MagicMock(),
        audit_repo=MagicMock(),
        agent_repo=MagicMock(get=MagicMock(return_value=MagicMock(default_model=None))),
        user_repo=MagicMock(),
        connector_repo=MagicMock(),
        dispatcher=SlashDispatcher(),
        usage_repo=None,
        gateway=None,
    )


def test_team_host_blocks_mcp_helper() -> None:
    assert team_host_blocks_mcp(_team_row()) is True
    assert team_host_blocks_mcp(_expert_row()) is False
    assert team_host_blocks_mcp(None) is False
    team_host_mcp_must_be_empty(_team_row())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "explicit,apply_defaults,label",
    [
        (None, True, "default_open_path"),
        (["explicit-mcp"], True, "explicit_list"),
        ([], False, "dashboard_empty_opt_out"),
        (["jdcloud-mon"], False, "explicit_cloud_mcp"),
    ],
)
async def test_resolve_returns_none_for_team_host_matrix(
    explicit: list[str] | None,
    apply_defaults: bool | None,
    label: str,
) -> None:
    """Expert defaults / default_open / explicit picks never reach merge on host."""
    agent_manager = MagicMock()
    agent_manager.get_row = MagicMock(return_value=_team_row())
    agent_manager.default_mcp_servers = MagicMock(return_value=["expert-listed-mcp"])
    agent_manager.merge_turn_mcp_servers = MagicMock(return_value=["should-not-matter"])
    agent_manager.prepare_chat_mcp = AsyncMock(return_value=[])
    # Simulate 0025 device pack API existing on the manager — must not be consulted.
    agent_manager.device_mcp_pack_for_turn = MagicMock(return_value=(["device-pack-mcp"], []))

    processor = _processor(agent_manager)
    result = await processor._resolve_turn_mcp_servers(
        agent_id="host-1",
        user_id=1,
        explicit=explicit,
        apply_defaults=apply_defaults,
    )
    assert result is None, label
    agent_manager.merge_turn_mcp_servers.assert_not_called()
    agent_manager.prepare_chat_mcp.assert_not_awaited()
    agent_manager.device_mcp_pack_for_turn.assert_not_called()
    agent_manager.default_mcp_servers.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_still_merges_for_non_host() -> None:
    agent_manager = MagicMock()
    agent_manager.get_row = MagicMock(return_value=_expert_row())
    agent_manager.default_mcp_servers = MagicMock(return_value=["expert-mcp"])
    agent_manager.merge_turn_mcp_servers = MagicMock(return_value=["expert-mcp", "open-mcp"])
    agent_manager.prepare_chat_mcp = AsyncMock(return_value=[])

    processor = _processor(agent_manager)
    result = await processor._resolve_turn_mcp_servers(
        agent_id="expert-1",
        user_id=1,
        explicit=None,
        apply_defaults=True,
    )
    assert result == ["expert-mcp", "open-mcp"]
    agent_manager.merge_turn_mcp_servers.assert_called_once()
    agent_manager.prepare_chat_mcp.assert_awaited_once()


@pytest.mark.asyncio
async def test_dashboard_metadata_cannot_force_mcp_on_team_host() -> None:
    agent_manager = MagicMock()
    agent_manager.get_row = MagicMock(return_value=_team_row())
    agent_manager.default_mcp_servers = MagicMock(return_value=["expert-mcp"])
    agent_manager.default_knowledge_base_ids = MagicMock(return_value=[])
    agent_manager.merge_turn_mcp_servers = MagicMock(return_value=["forced"])
    agent_manager.prepare_chat_mcp = AsyncMock(return_value=[])
    agent_manager.device_mcp_pack_for_turn = MagicMock(return_value=(["pack"], []))
    providers = MagicMock()
    providers.is_model_ref_usable = MagicMock(return_value=False)
    providers.resolve_explicit_default_model = MagicMock(return_value=None)
    providers.resolve_model_for_multimodal_turn = MagicMock(side_effect=lambda ref, **_k: ref)
    agent_manager.providers_for_agent.return_value = providers
    agent_manager.get_thread_model = MagicMock(return_value=None)

    processor = _processor(agent_manager)
    msg = InboundMessage(
        channel_id="ws",
        channel_type="dashboard",
        tenant_id="host-1",
        channel_subject=ChannelSubject(subject_id="1"),
        content=[TextContent(text="hi")],
        metadata={"mcp_servers": ["jdcloud-mon", "docs__1"]},
    )
    request = await processor._build_dashboard_request(
        msg,
        agent_id="host-1",
        user_id=1,
        session_key="sk",
        thread_id="thr",
        meta=msg.metadata or {},
    )
    assert "mcp_servers" not in request
    agent_manager.merge_turn_mcp_servers.assert_not_called()
    agent_manager.device_mcp_pack_for_turn.assert_not_called()
