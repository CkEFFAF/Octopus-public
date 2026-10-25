"""0038 F02 backend path jail without workspace_root policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.resource_policy import raise_if_backend_outside_user_root


class _EmptyPolicyRepo:
    def get(self, user_id: int, name: str):  # noqa: ARG002
        return None


def test_non_admin_without_policy_cannot_use_host_tmp(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(OctopError) as ei:
        raise_if_backend_outside_user_root(
            _EmptyPolicyRepo(),
            1,
            {"type": "local_shell", "root_dir": str(outside)},
            is_admin=False,
        )
    assert ei.value.code in (
        ErrorCode.FORBIDDEN,
        ErrorCode.WORKSPACE_ROOT_RESTRICTED,
        ErrorCode.WORKSPACE_OP_UNSUPPORTED,
    )


def test_admin_without_policy_may_use_host_path(tmp_path) -> None:
    target = tmp_path / "admin-ok"
    target.mkdir()
    raise_if_backend_outside_user_root(
        _EmptyPolicyRepo(),
        1,
        {"type": "local_shell", "root_dir": str(target)},
        is_admin=True,
    )


def test_non_admin_may_use_path_under_home(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    nested = home / "work"
    nested.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    raise_if_backend_outside_user_root(
        _EmptyPolicyRepo(),
        1,
        {"type": "local_shell", "root_dir": str(nested)},
        is_admin=False,
    )


def test_non_admin_cannot_bind_control_plane_agents_tree(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    agents = home / ".octop" / "agents" / "main"
    agents.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    with pytest.raises(OctopError) as ei:
        raise_if_backend_outside_user_root(
            _EmptyPolicyRepo(),
            1,
            {"type": "local_shell", "root_dir": str(agents)},
            is_admin=False,
        )
    assert ei.value.code in (
        ErrorCode.FORBIDDEN,
        ErrorCode.WORKSPACE_ROOT_RESTRICTED,
        ErrorCode.WORKSPACE_OP_UNSUPPORTED,
    )


def test_admin_may_bind_control_plane_agents_tree(tmp_path) -> None:
    agents = tmp_path / ".octop" / "agents" / "main"
    agents.mkdir(parents=True)
    raise_if_backend_outside_user_root(
        _EmptyPolicyRepo(),
        1,
        {"type": "local_shell", "root_dir": str(agents)},
        is_admin=True,
    )
