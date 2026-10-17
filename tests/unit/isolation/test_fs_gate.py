"""0028 AC-I02: bwrap gate for scoped root_dir."""

from __future__ import annotations

import pytest

from octop.infra.isolation.fs_gate import (
    assert_local_fs_isolation,
    evaluate_local_fs_isolation,
    require_bwrap_enabled,
)


def test_require_bwrap_env_knobs() -> None:
    assert require_bwrap_enabled(env={"OCTOP_REQUIRE_BWRAP": "1"}) is True
    assert require_bwrap_enabled(env={"OCTOP_REQUIRE_BWRAP": "0"}) is False
    assert require_bwrap_enabled(env={"OCTOP_ENV": "production"}) is True
    assert require_bwrap_enabled(env={"OCTOP_PRODUCTION": "true"}) is True
    assert require_bwrap_enabled(env={}) is False


def test_host_root_allows_without_bwrap() -> None:
    decision = evaluate_local_fs_isolation(
        {"type": "local_shell", "root_dir": "/", "virtual_mode": True},
        platform="linux",
        bwrap_on_path=False,
        require_bwrap=True,
    )
    assert decision.mode == "allow"


def test_scoped_root_rejects_when_required_and_missing_bwrap() -> None:
    decision = evaluate_local_fs_isolation(
        {"type": "local_shell", "root_dir": "/home/u/OctopData/agents/a1", "virtual_mode": True},
        platform="linux",
        bwrap_on_path=False,
        require_bwrap=True,
    )
    assert decision.mode == "reject"
    assert decision.ok is False
    with pytest.raises(PermissionError, match="bubblewrap"):
        assert_local_fs_isolation(
            {"type": "local_shell", "root_dir": "/tmp/ws", "virtual_mode": True},
            platform="linux",
            bwrap_on_path=False,
            require_bwrap=True,
        )


def test_scoped_root_degrades_when_require_off() -> None:
    decision = evaluate_local_fs_isolation(
        {"type": "filesystem", "root_dir": "/var/octop/ws", "virtual_mode": True},
        platform="linux",
        bwrap_on_path=False,
        require_bwrap=False,
    )
    assert decision.mode == "degrade"
    assert decision.ok is True


def test_scoped_root_allows_when_bwrap_present() -> None:
    decision = evaluate_local_fs_isolation(
        {"type": "local_shell", "root_dir": "/data/ws", "virtual_mode": True},
        platform="linux",
        bwrap_on_path=True,
        require_bwrap=True,
    )
    assert decision.mode == "allow"


def test_docker_backend_not_gated() -> None:
    decision = evaluate_local_fs_isolation(
        {"type": "docker", "image": "octop:latest"},
        platform="linux",
        bwrap_on_path=False,
        require_bwrap=True,
    )
    assert decision.mode == "allow"


def test_composite_uses_default() -> None:
    decision = evaluate_local_fs_isolation(
        {
            "type": "composite",
            "default": {
                "type": "local_shell",
                "root_dir": "/scoped",
                "virtual_mode": True,
            },
        },
        platform="linux",
        bwrap_on_path=False,
        require_bwrap=True,
    )
    assert decision.mode == "reject"
