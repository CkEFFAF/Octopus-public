"""Execution isolation (0028): team-host MCP invariant, FS jail gate, egress skeleton."""

from __future__ import annotations

from octop.infra.isolation.egress import (
    EgressHook,
    EgressPolicy,
    default_management_egress_policy,
    is_management_egress_allowed,
    load_egress_policy_from_env,
)
from octop.infra.isolation.fs_gate import (
    FsIsolationDecision,
    assert_local_fs_isolation,
    evaluate_local_fs_isolation,
    require_bwrap_enabled,
)
from octop.infra.isolation.home_guard import (
    PRODUCTION_MARKER_NAME,
    HomeSeparationResult,
    check_dev_prod_home_separation,
    is_production_home,
    write_production_marker,
)
from octop.infra.isolation.team_host_mcp import (
    team_host_blocks_mcp,
    team_host_mcp_must_be_empty,
)

__all__ = [
    "PRODUCTION_MARKER_NAME",
    "EgressHook",
    "EgressPolicy",
    "FsIsolationDecision",
    "HomeSeparationResult",
    "assert_local_fs_isolation",
    "check_dev_prod_home_separation",
    "default_management_egress_policy",
    "evaluate_local_fs_isolation",
    "is_management_egress_allowed",
    "is_production_home",
    "load_egress_policy_from_env",
    "require_bwrap_enabled",
    "team_host_blocks_mcp",
    "team_host_mcp_must_be_empty",
    "write_production_marker",
]
