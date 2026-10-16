"""0019 S1/S3/S4: default_target visibility, room host selection, target_policy."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.config import var_child_runnable_config

from octop.infra.agents.teams.device_context import restore_peer_context
from octop.infra.agents.teams.service import TeamService
from octop.infra.agents.teams.target_visibility import (
    apply_target_policy,
    enrich_peer_metadata,
    expert_default_target,
    install_harness_target_patches,
)
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.agents import AgentRepo
from octop.infra.db.repos.users import UserRepo
from octop.infra.db.services import RepoBundle
from octop.infra.execution.service import ExecutionService


class _PathWorkspace:
    def __init__(self, root: Path) -> None:
        self.root = root

    def read_text(self, path: str, *, limit: int = 10_000_000) -> str | None:
        target = self.root / path
        if not target.is_file():
            return None
        return target.read_text(encoding="utf-8")

    def write_text(self, path: str, content: str, *, force: bool = False) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def test_expert_default_target_shapes() -> None:
    assert expert_default_target(device_binding=None) is None
    assert expert_default_target(device_binding={}) is None
    assert expert_default_target(
        device_binding={"target_kind": "local", "working_dir": "/tmp"}
    ) == {
        "target_kind": "local",
        "device_id": None,
        "device_name": None,
        "working_dir": "/tmp",
    }
    assert expert_default_target(device_binding={"device_id": "d1"}, device_name="GPU") == {
        "target_kind": "device",
        "device_id": "d1",
        "device_name": "GPU",
        "working_dir": None,
    }


def test_apply_target_policy_member_default_strips_inherited_device() -> None:
    snap = {
        "owner": 1,
        "configurable": {
            "octop_device_target": {"device_id": "pc", "grant_version": 1},
            "octop_execution_context": {"context_id": "c1"},
            "octop_task_run_id": "run",
        },
    }
    out = apply_target_policy(snap, policy="member_default")
    assert "octop_device_target" not in out["configurable"]
    assert "octop_execution_context" not in out["configurable"]
    assert out["configurable"]["octop_target_policy"] == "member_default"
    # inherit keeps parent target
    kept = apply_target_policy(snap, policy="inherit")
    assert kept["configurable"]["octop_device_target"]["device_id"] == "pc"


def test_apply_target_policy_explicit_uses_device_grant(devices_owned: None = None) -> None:
    device = SimpleNamespace(grant_version=9)
    devices = SimpleNamespace(owned=lambda owner, did: device)
    snap = {
        "owner": 1,
        "configurable": {
            "octop_device_target": {"device_id": "old", "grant_version": 1},
        },
    }
    out = apply_target_policy(
        snap,
        policy="explicit",
        explicit={"device_id": "new", "target_kind": "device"},
        devices=devices,
        owner=1,
    )
    assert out["configurable"]["octop_device_target"] == {
        "device_id": "new",
        "grant_version": 9,
    }
    assert out["configurable"]["octop_target_policy"] == "explicit"


def test_team_payload_exposes_default_target_and_model(tmp_path: Path) -> None:
    db = SqlitePool(tmp_path / "t.db")
    run_migrations(db)
    users = UserRepo(db)
    users.create(username="owner", password_hash="h", role="user")
    agents = AgentRepo(db)
    agents.create(agent_id="host", user_id=1, name="Host", kind="team")
    agents.create(
        agent_id="a",
        user_id=1,
        name="Alpha",
        default_model="openai/gpt-test",
        config_json=json.dumps(
            {"device_binding": {"device_id": "dev-a", "working_dir": "/a"}},
            ensure_ascii=False,
        ),
    )
    agents.create(agent_id="b", user_id=1, name="Beta")
    repos = RepoBundle.from_pool(db)
    workspaces = tmp_path / "ws"

    def workspace_for(agent_id: str) -> _PathWorkspace:
        return _PathWorkspace(workspaces / agent_id)

    teams = TeamService(repos, workspace_for=workspace_for)
    teams.replace_members("host", ["a", "b"])
    payload = teams.team_payload(agents.get("host"))
    by_id = {m["agent_id"]: m for m in payload["members"]}
    assert by_id["a"]["model_ref"] == "openai/gpt-test"
    assert by_id["a"]["default_target"]["device_id"] == "dev-a"
    assert by_id["b"]["default_target"] is None
    assert by_id["b"]["model_ref"] is None
    db.close()


def test_room_host_selection_does_not_mutate_member_bindings(tmp_path: Path) -> None:
    """AC-03: host thread selection is room unify; member config_json unchanged."""
    from octop.infra.devices.service import DeviceService

    db = SqlitePool(tmp_path / "sel.db")
    run_migrations(db)
    repos = RepoBundle.from_pool(db)
    owner = repos.user_repo.create(username="owner", role="admin", password_hash="x")
    repos.agent_repo.create(
        agent_id="member",
        user_id=owner,
        name="Member",
        config_json=json.dumps({"device_binding": {"device_id": "keep-me"}}),
    )
    repos.agent_repo.create(agent_id="host", user_id=owner, name="Host", kind="team")
    repos.thread_repo.insert(
        thread_id="room",
        user_id=owner,
        agent_id="host",
        channel_type="dashboard",
        session_key="room",
    )
    before = repos.agent_repo.get("member").config_json
    # Simulate room unify via host thread selection only (no device enroll needed for save of null/local path).
    # Use account-less selection with work_mode only then clear device — still must not touch member.
    devices = DeviceService(repos)
    executions = ExecutionService(devices)
    # Saving a device selection requires an owned device; enroll a minimal one.
    enrolled = devices.enroll(
        owner_user_id=owner,
        name="gpu",
        platform="linux",
        capabilities=["files_read"],
        permissions=["files_read"],
        roots=[],
        trust_mode="restricted",
    )
    device_id = enrolled["device"]["device_id"]
    executions.save_selection(
        owner, "room", {"device_id": device_id, "working_dir": "/room", "work_mode": "agentic"}
    )
    after = repos.agent_repo.get("member").config_json
    assert after == before
    assert json.loads(after)["device_binding"]["device_id"] == "keep-me"
    sel = executions.selection(owner, "room")
    assert sel["device_id"] == device_id
    db.close()


def test_agent_list_item_patch_surfaces_metadata() -> None:
    install_harness_target_patches()
    from octop_harness.teams import tools as team_tools

    entry = SimpleNamespace(
        agent_id="ABCDEF123456",
        metadata={
            "description": "helper",
            "default_target": {"target_kind": "device", "device_id": "d1", "device_name": "GPU"},
            "model_ref": "m/ref",
        },
    )
    team = SimpleNamespace(peer_display_name=lambda e: "Alpha")
    item = team_tools._agent_list_item(team, entry, "en")
    assert item["default_target"]["device_id"] == "d1"
    assert item["model_ref"] == "m/ref"


def test_enrich_peer_metadata_sets_fields() -> None:
    row = SimpleNamespace(
        default_model="x/y",
        config_json=json.dumps({"device_binding": {"device_id": "z"}}),
    )
    meta: dict = {}
    enrich_peer_metadata(meta, row=row, device_name="Box")
    assert meta["model_ref"] == "x/y"
    assert meta["default_target"]["device_name"] == "Box"


@pytest.mark.asyncio
async def test_restore_peer_context_respects_member_default_policy() -> None:
    """member_default snapshot has no parent device; restore must not invent one."""
    token = var_child_runnable_config.set({"configurable": {"user": "1"}})
    try:
        # Simulate tracker context after member_default strip.
        from octop.infra.agents.teams import device_context as dc

        ctx = {
            "owner": 1,
            "configurable": {"octop_target_policy": "member_default", "octop_task_run_id": "r"},
            "devices": SimpleNamespace(owned=lambda *a, **k: pytest.fail("should not own")),
        }
        t = dc._context.set(ctx)
        try:
            req = restore_peer_context({"user": "1", "configurable": {}})
            assert "octop_device_target" not in (req.get("configurable") or {})
        finally:
            dc._context.reset(t)
    finally:
        var_child_runnable_config.reset(token)
