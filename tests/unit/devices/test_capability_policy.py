"""0025 S0: device capability policy parsing, merge matrix, peek device_id."""

from __future__ import annotations

from typing import Any

import pytest

from octop.infra.connectors.default_open import merge_mcp_servers_with_defaults
from octop.infra.connectors.service import ConnectorService
from octop.infra.devices.capability_policy import (
    dump_capability_policy,
    parse_capability_policy,
    policy_missing_mcp,
    seed_mcp_into_policy,
    validate_capability_policy_shape,
)


def test_parse_and_dump_roundtrip() -> None:
    assert parse_capability_policy(None)["mcp_servers"] == []
    assert dump_capability_policy({"mcp_servers": []}) is None
    raw = dump_capability_policy({"mcp_servers": ["jdcloud-mon", "jdcloud-mon", ""]})
    assert raw is not None
    assert parse_capability_policy(raw)["mcp_servers"] == ["jdcloud-mon"]


def test_validate_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="unknown keys"):
        validate_capability_policy_shape({"mcp_servers": ["a"], "extra": 1})


def test_seed_mcp_idempotent() -> None:
    first = seed_mcp_into_policy(None, mcp_servers=["jdcloud-mon"])
    second = seed_mcp_into_policy(first, mcp_servers=["jdcloud-mon"])
    assert first["mcp_servers"] == second["mcp_servers"] == ["jdcloud-mon"]


def test_policy_missing_mcp() -> None:
    policy = parse_capability_policy({"mcp_servers": ["jdcloud-mon", "ok"]})
    assert policy_missing_mcp(policy, {"ok"}) == ["jdcloud-mon"]


class _Svc:
    def list_default_open_mcp_server_names(self, _uid: int) -> list[str]:
        return ["account_open"]

    def list_active_mcp_server_names(self, _uid: int) -> list[str]:
        return ["account_open", "expert", "jdcloud-mon", "gpu_only"]


def _merge(**kwargs: Any) -> list[str] | None:
    return ConnectorService.merge_turn_mcp_servers(_Svc(), 1, **kwargs)  # type: ignore[arg-type]


def test_ac_c01_device_pack_on_im_defaults() -> None:
    """Cloud device pack contributes when expert list empty and default_open off."""

    class _NoAccount(_Svc):
        def list_default_open_mcp_server_names(self, _uid: int) -> list[str]:
            return []

    merged = ConnectorService.merge_turn_mcp_servers(  # type: ignore[arg-type]
        _NoAccount(),
        1,
        None,
        apply_defaults=True,
        extra_defaults=[],
        device_defaults=["jdcloud-mon"],
    )
    assert merged == ["jdcloud-mon"]


def test_ac_c02_other_device_no_leak() -> None:
    class _NoAccount(_Svc):
        def list_default_open_mcp_server_names(self, _uid: int) -> list[str]:
            return []

    merged = ConnectorService.merge_turn_mcp_servers(  # type: ignore[arg-type]
        _NoAccount(),
        1,
        None,
        apply_defaults=True,
        extra_defaults=[],
        device_defaults=["gpu_only"],
    )
    assert merged == ["gpu_only"]
    assert "jdcloud-mon" not in (merged or [])


def test_ac_c03_unbind_drops_device_only() -> None:
    class _NoAccount(_Svc):
        def list_default_open_mcp_server_names(self, _uid: int) -> list[str]:
            return []

    before = ConnectorService.merge_turn_mcp_servers(  # type: ignore[arg-type]
        _NoAccount(),
        1,
        None,
        apply_defaults=True,
        extra_defaults=[],
        device_defaults=["jdcloud-mon"],
    )
    after = ConnectorService.merge_turn_mcp_servers(  # type: ignore[arg-type]
        _NoAccount(),
        1,
        None,
        apply_defaults=True,
        extra_defaults=[],
        device_defaults=[],
    )
    assert before == ["jdcloud-mon"]
    assert after is None


def test_ac_c04_dashboard_empty_opts_out_account_and_device() -> None:
    merged = _merge(
        explicit=[],
        apply_defaults=False,
        extra_defaults=["expert"],
        device_defaults=["jdcloud-mon"],
    )
    assert merged is None
    assert merge_mcp_servers_with_defaults([], ["a"], apply_defaults=False) is None


def test_ac_c05_unavailable_device_name_filtered() -> None:
    class _Svc2(_Svc):
        def list_default_open_mcp_server_names(self, _uid: int) -> list[str]:
            return []

        def list_active_mcp_server_names(self, _uid: int) -> list[str]:
            return ["expert"]

    merged = ConnectorService.merge_turn_mcp_servers(  # type: ignore[arg-type]
        _Svc2(),
        1,
        None,
        apply_defaults=True,
        device_defaults=["jdcloud-mon", "expert"],
    )
    assert merged == ["expert"]


def test_ac_c09_union_idempotent() -> None:
    class _NoAccount(_Svc):
        def list_default_open_mcp_server_names(self, _uid: int) -> list[str]:
            return []

    merged = ConnectorService.merge_turn_mcp_servers(  # type: ignore[arg-type]
        _NoAccount(),
        1,
        None,
        apply_defaults=True,
        extra_defaults=["jdcloud-mon"],
        device_defaults=["jdcloud-mon"],
    )
    assert merged == ["jdcloud-mon"]


def test_deny_removes_after_union() -> None:
    merged = _merge(
        explicit=None,
        apply_defaults=True,
        extra_defaults=["expert"],
        device_defaults=["jdcloud-mon"],
        deny_mcp_servers=["jdcloud-mon"],
    )
    assert merged == ["account_open", "expert"]
