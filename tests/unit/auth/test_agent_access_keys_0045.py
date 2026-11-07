"""0045 unit: agent access keys lifecycle, principal, key-login rejection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from octop.infra.auth.agent_access_keys import (
    AGENT_KEY_PREFIX,
    AGENT_SCOPES,
    AgentAccessKeyService,
)
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError


@pytest.fixture
def repos(tmp_path: Path) -> RepoBundle:
    pool = SqlitePool(tmp_path / "aak.db")
    run_migrations(pool)
    return RepoBundle.from_pool(pool)


@pytest.fixture
def owner(repos: RepoBundle) -> int:
    return repos.user_repo.create(username="owner", role="admin", password_hash="x")


def _svc(repos: RepoBundle) -> AgentAccessKeyService:
    return AgentAccessKeyService(repos)


def test_create_lists_without_secret(repos: RepoBundle, owner: int) -> None:
    svc = _svc(repos)
    created = svc.create(
        owner,
        name="zed",
        days=30,
        scopes=sorted(AGENT_SCOPES),
        expert_ids=["expert-1"],
    )
    assert created["secret"].startswith(AGENT_KEY_PREFIX)
    assert "secret_hash" not in created["key"]
    listed = svc.list_keys(owner)
    assert len(listed) == 1
    assert "secret" not in listed[0]
    assert listed[0]["prefix"] == AGENT_KEY_PREFIX
    assert set(listed[0]["scopes"]) == AGENT_SCOPES


def test_empty_scopes_rejected(repos: RepoBundle, owner: int) -> None:
    with pytest.raises(OctopError) as ei:
        _svc(repos).create(owner, name="x", days=7, scopes=[], expert_ids=["e1"])
    assert ei.value.status == 422


def test_empty_experts_rejected(repos: RepoBundle, owner: int) -> None:
    with pytest.raises(OctopError) as ei:
        _svc(repos).create(owner, name="x", days=7, scopes=["tasks.read"], expert_ids=[])
    assert ei.value.status == 422


def test_authenticate_and_revoke(repos: RepoBundle, owner: int) -> None:
    svc = _svc(repos)
    created = svc.create(
        owner,
        name="lap",
        days=30,
        scopes=["tasks.create", "tasks.read"],
        expert_ids=["e1", "e2"],
    )
    principal = svc.authenticate(created["secret"], "127.0.0.1")
    assert principal.actor_kind == "machine"
    assert principal.owner_user_id == owner
    assert principal.has_scope("tasks.create")
    assert principal.allows_expert("e1")
    assert not principal.allows_expert("e9")
    svc.revoke(owner, created["key"]["key_id"])
    with pytest.raises(OctopError) as ei:
        svc.authenticate(created["secret"], "127.0.0.1")
    assert ei.value.code is ErrorCode.AUTH_FAILED


def test_oak_prefix_rejected_as_agent(repos: RepoBundle, owner: int) -> None:
    svc = _svc(repos)
    with pytest.raises(OctopError):
        svc.authenticate("oak_" + "x" * 40, "127.0.0.1")


def test_object_grants(repos: RepoBundle, owner: int) -> None:
    svc = _svc(repos)
    created = svc.create(
        owner,
        name="g",
        days=7,
        scopes=["tasks.read"],
        expert_ids=["e1"],
    )
    principal = svc.authenticate(created["secret"], "127.0.0.1")
    assert not svc.owns_object(principal, "work_item", "t1")
    svc.grant_object(principal, "work_item", "t1")
    assert svc.owns_object(principal, "work_item", "t1")


def test_public_never_includes_hash(repos: RepoBundle, owner: int) -> None:
    svc = _svc(repos)
    created = svc.create(owner, name="p", days=7, scopes=["experts.read"], expert_ids=["e1"])
    blob = json.dumps(created["key"])
    assert "secret_hash" not in blob
    assert AGENT_KEY_PREFIX not in blob or created["key"]["prefix"] == AGENT_KEY_PREFIX
