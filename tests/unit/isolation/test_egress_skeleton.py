"""0028 S0 egress allowlist skeleton (AC-I04 deferred to S1)."""

from __future__ import annotations

import json
from pathlib import Path

from octop.infra.isolation.egress import (
    EgressPolicy,
    default_management_egress_policy,
    is_management_egress_allowed,
    load_egress_policy_from_env,
)


def test_default_policy_disabled_allows_all() -> None:
    policy = default_management_egress_policy()
    assert policy.enabled is False
    assert is_management_egress_allowed("https://evil.example/", policy=policy) is True


def test_enabled_policy_filters_hosts() -> None:
    policy = EgressPolicy(
        allow_hosts=("api.openai.com",),
        allow_suffixes=("anthropic.com",),
        enabled=True,
    )
    assert is_management_egress_allowed("https://api.openai.com/v1", policy=policy)
    assert is_management_egress_allowed("https://api.anthropic.com/v1", policy=policy)
    assert is_management_egress_allowed("https://evil.example/", policy=policy) is False


def test_load_from_json_env() -> None:
    raw = json.dumps(
        {
            "enabled": True,
            "allow_hosts": ["updates.example.com"],
            "allow_suffixes": [],
        }
    )
    policy = load_egress_policy_from_env(env={"OCTOP_EGRESS_ALLOWLIST_JSON": raw})
    assert policy.enabled is True
    assert is_management_egress_allowed("https://updates.example.com/x", policy=policy)
    assert is_management_egress_allowed("https://other.example/", policy=policy) is False


def test_load_from_path(tmp_path: Path) -> None:
    path = tmp_path / "egress.json"
    path.write_text(
        json.dumps({"enabled": True, "allow_suffixes": ["example.com"]}),
        encoding="utf-8",
    )
    policy = load_egress_policy_from_env(
        env={"OCTOP_EGRESS_ALLOWLIST_PATH": str(path)},
    )
    assert is_management_egress_allowed("https://a.example.com/", policy=policy)
