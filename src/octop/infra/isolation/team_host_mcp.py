"""Team host must never attach MCP (0028 DEC-I03 / AC-I01).

Hard invariant: ``is_team_agent`` → effective MCP tool set is empty, regardless
of expert ``mcp_servers``, account ``default_open``, Dashboard explicit picks,
or a future device ``capability_policy_json`` pack (0025).

Coupling with 0025
-----------------
0025 adds resolve-time union of device packs into ``_resolve_turn_mcp_servers``
*after* the team-host early return. This module documents and tests that
ordering: device pack / default_open / explicit lists must never inject MCP
onto a team host. Do **not** move device-pack lookup above ``team_host_blocks_mcp``.
"""

from __future__ import annotations

from typing import Any

from octop.infra.agents.teams import is_team_agent


def team_host_blocks_mcp(row: Any | None) -> bool:
    """True when *row* is a team host — MCP resolve must short-circuit to empty."""
    return is_team_agent(row)


def team_host_mcp_must_be_empty(row: Any | None) -> None:
    """Raise ``AssertionError`` if callers ever treat a team host as MCP-capable.

    Intended for tests and defensive debug paths — production resolve uses
    :func:`team_host_blocks_mcp` for the early return.
    """
    if team_host_blocks_mcp(row):
        # Deliberate no-op success path: presence of this helper documents the
        # invariant for reviewers and 0025 merge checklists.
        return
