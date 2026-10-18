"""Dispatch options must survive the middleware actually used by running agents."""

from types import SimpleNamespace

import pytest
from octop_harness.middleware.peer import PeerAgentMiddleware
from octop_harness.teams.team_manager import TeamManager
from pydantic import ValidationError


@pytest.mark.parametrize("mode", ["sync", "async", "both"])
def test_runtime_tool_entries_preserve_target_policy_and_reject_typos(mode):
    team = SimpleNamespace(enabled=True)
    middleware = PeerAgentMiddleware(team, peer_invoke_mode=mode)
    for tools in (middleware.tools, TeamManager.team_tools(team, peer_invoke_mode=mode)):
        ask = next(tool for tool in tools if tool.name == "ask_agent")
        value = ask.args_schema.model_validate(
            {"expert": "cloud", "message": "read paper", "target_policy": "member_default"}
        )
        assert value.model_dump()["target_policy"] == "member_default"
        with pytest.raises(ValidationError):
            ask.args_schema.model_validate(
                {"expert": "cloud", "message": "read paper", "target_polciy": "explicit"}
            )
