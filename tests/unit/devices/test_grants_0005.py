"""0005 device permission expansion: defaults, owner_auto, confirm, ceilings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.devices.executor import DeviceExecutor
from octop.infra.devices.protocol import DEFAULT_ENROLL_PERMISSIONS, merge_enroll_permissions
from octop.infra.devices.service import DeviceService
from octop.infra.errors import ErrorCode, OctopError


@pytest.fixture
def rig(tmp_path: Path) -> Any:
    pool = SqlitePool(tmp_path / "control.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="owner", role="admin", password_hash="unused")
    other = repos.user_repo.create(username="other", role="user", password_hash="unused")
    service = DeviceService(repos)
    yield service, owner, other, tmp_path
    pool.close()


def enroll(
    service: DeviceService,
    owner: int,
    *,
    capabilities: list[str] | None = None,
    permissions: list[str] | None = None,
    roots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    caps = capabilities or [
        "desktop_view",
        "desktop_control",
        "files_read",
        "files_write",
        "command_exec",
        "acp_run",
    ]
    return service.enroll(
        pairing_code=service.pairing(owner)["pairing_code"],
        name="Device",
        platform="windows",
        capabilities=caps,
        permissions=permissions or [],
        roots=roots or [],
    )


async def connect_v2(
    service: DeviceService, enrolled: dict[str, Any], executor: DeviceExecutor
) -> Any:
    device_id = enrolled["device"]["device_id"]
    connection: Any = None
    proposals: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        if frame["type"] in {"hello_ack", "grants"}:
            executor.update_grants(frame["grant_version"], frame["permissions"], frame["roots"])
        elif frame["type"] == "grant_proposal":
            proposals.append(frame)
            try:
                executor.apply_grant_proposal(frame["permissions"], frame["roots"])
                decision = "accept"
            except Exception:
                decision = "reject"
            await service.receive(
                connection,
                {
                    "type": "grant_resolve",
                    "proposal_id": frame["proposal_id"],
                    "decision": decision,
                },
            )

    async def close() -> None:
        await executor.close()

    connection = await service.connect(
        device_id,
        enrolled["device_token"],
        send,
        close,
        client_protocol_version=2,
    )
    connection.proposals = proposals
    return connection


def test_merge_enroll_permissions_defaults() -> None:
    caps = ["desktop_view", "desktop_control", "files_read", "files_write", "command_exec"]
    assert set(merge_enroll_permissions(caps, [])) == DEFAULT_ENROLL_PERMISSIONS
    assert "files_write" in merge_enroll_permissions(caps, ["files_write"])
    assert "command_exec" not in merge_enroll_permissions(caps, [])


def test_enroll_applies_req007_defaults(rig: Any) -> None:
    service, owner, _, _ = rig
    item = enroll(service, owner, permissions=[])
    perms = set(item["device"]["permissions"])
    assert perms == {"desktop_view", "desktop_control", "files_read"}
    assert item["device"]["remote_grant_mode"] == "owner_auto"


def test_enroll_empty_roots_keeps_files_read(rig: Any) -> None:
    service, owner, _, _ = rig
    item = enroll(service, owner, permissions=[])
    assert "files_read" in item["device"]["permissions"]
    assert item["device"]["roots"] == []


@pytest.mark.asyncio
async def test_owner_auto_expands_files_write_when_online(rig: Any) -> None:
    service, owner, _, tmp = rig
    share = tmp / "share"
    share.mkdir()
    root = {
        "id": "shared",
        "name": "Shared",
        "path": str(share),
        "read": True,
        "write": True,
    }
    item = enroll(
        service,
        owner,
        permissions=["files_read"],
        roots=[root],
    )
    executor = DeviceExecutor(
        ["files_read"],
        [root],
        state_dir=tmp / "state",
        desktop_enabled=True,
        control_enabled=True,
    )
    await connect_v2(service, item, executor)
    device_id = item["device"]["device_id"]
    updated = await service.update(
        owner, device_id, permissions=["desktop_view", "desktop_control", "files_read", "files_write"]
    )
    assert "files_write" in updated["permissions"]
    assert updated.get("pending_proposal") is None


@pytest.mark.asyncio
async def test_command_exec_requires_device_confirm(rig: Any) -> None:
    service, owner, _, tmp = rig
    share = tmp / "share"
    share.mkdir()
    root = {
        "id": "shared",
        "name": "Shared",
        "path": str(share),
        "read": True,
        "write": True,
    }
    item = enroll(service, owner, permissions=[], roots=[root])
    executor = DeviceExecutor(
        ["files_read", "desktop_view", "desktop_control"],
        [root],
        state_dir=tmp / "state",
        desktop_enabled=True,
        control_enabled=True,
        command_enabled=True,
    )
    connection = await connect_v2(service, item, executor)
    device_id = item["device"]["device_id"]
    # Desired includes command_exec -> proposal path; connect_v2 auto-accepts.
    updated = await service.update(
        owner,
        device_id,
        permissions=[
            "desktop_view",
            "desktop_control",
            "files_read",
            "command_exec",
        ],
    )
    assert "command_exec" in updated["permissions"]
    assert connection.proposals, "expected grant_proposal for command_exec"


@pytest.mark.asyncio
async def test_expand_rejects_unsupported_capability(rig: Any) -> None:
    service, owner, _, _ = rig
    item = enroll(
        service,
        owner,
        capabilities=["files_read"],
        permissions=[],
    )
    device_id = item["device"]["device_id"]
    with pytest.raises(OctopError) as exc:
        await service.update(owner, device_id, permissions=["files_read", "desktop_view"])
    assert exc.value.code == ErrorCode.DEVICE_INVALID
    assert "UNSUPPORTED_CAPABILITY" in str(exc.value)


@pytest.mark.asyncio
async def test_non_owner_forbidden(rig: Any) -> None:
    service, owner, other, _ = rig
    item = enroll(service, owner, permissions=[])
    with pytest.raises(OctopError) as exc:
        await service.update(other, item["device"]["device_id"], permissions=[])
    assert exc.value.code == ErrorCode.NOT_FOUND


@pytest.mark.asyncio
async def test_owner_auto_offline_expand_fails(rig: Any) -> None:
    service, owner, _, _ = rig
    item = enroll(service, owner, permissions=[])
    device_id = item["device"]["device_id"]
    with pytest.raises(OctopError) as exc:
        await service.update(
            owner,
            device_id,
            permissions=["desktop_view", "desktop_control", "files_read", "files_write"],
        )
    assert exc.value.code == ErrorCode.DEVICE_OFFLINE


@pytest.mark.asyncio
async def test_legacy_client_outdated_on_high_risk(rig: Any) -> None:
    service, owner, _, tmp = rig
    share = tmp / "share"
    share.mkdir()
    root = {
        "id": "shared",
        "name": "Shared",
        "path": str(share),
        "read": True,
        "write": True,
    }
    item = enroll(service, owner, permissions=[], roots=[root])
    device_id = item["device"]["device_id"]

    async def send(frame: dict[str, Any]) -> None:
        return None

    async def close() -> None:
        return None

    await service.connect(
        device_id, item["device_token"], send, close, client_protocol_version=1
    )
    with pytest.raises(OctopError) as exc:
        await service.update(
            owner,
            device_id,
            permissions=["desktop_view", "desktop_control", "files_read", "command_exec"],
        )
    assert "CLIENT_OUTDATED" in str(exc.value)


@pytest.mark.asyncio
async def test_owner_http_resolve_cannot_silently_accept_high_risk(rig: Any) -> None:
    """DEC-005: owner HTTP accept must not land command_exec/acp_run without device confirm."""
    service, owner, _, tmp = rig
    share = tmp / "share"
    share.mkdir()
    root = {
        "id": "shared",
        "name": "Shared",
        "path": str(share),
        "read": True,
        "write": True,
    }
    item = enroll(service, owner, permissions=[], roots=[root])
    device_id = item["device"]["device_id"]
    # Create a pending high-risk proposal without auto-resolving on the wire.
    public = await service.create_grant_proposal(
        owner,
        device_id,
        permissions=[
            "desktop_view",
            "desktop_control",
            "files_read",
            "command_exec",
        ],
        roots=[root],
    )
    assert "command_exec" not in public["permissions"]
    pending = [
        p
        for p in service._proposals.values()
        if p.get("device_id") == device_id and p.get("status") == "pending"
    ]
    assert len(pending) == 1
    proposal_id = pending[0]["proposal_id"]
    with pytest.raises(OctopError) as exc:
        await service.resolve_grant_proposal(
            device_id, proposal_id, accept=True, owner=owner
        )
    assert exc.value.code == ErrorCode.FORBIDDEN
    assert "DEVICE_CONFIRM_REQUIRED" in str(exc.value)
    assert "DEC-005" in str(exc.value)
    fresh = service.repos.device_repo.get(device_id)
    assert fresh is not None
    assert "command_exec" not in fresh.permissions
    # Proposal stays pending so the device can still confirm.
    assert service._proposals[proposal_id]["status"] == "pending"


@pytest.mark.asyncio
async def test_owner_http_resolve_can_reject_high_risk(rig: Any) -> None:
    """Owner may reject a high-risk proposal via HTTP; only accept is blocked."""
    service, owner, _, tmp = rig
    share = tmp / "share"
    share.mkdir()
    root = {
        "id": "shared",
        "name": "Shared",
        "path": str(share),
        "read": True,
        "write": True,
    }
    item = enroll(service, owner, permissions=[], roots=[root])
    device_id = item["device"]["device_id"]
    await service.create_grant_proposal(
        owner,
        device_id,
        permissions=[
            "desktop_view",
            "desktop_control",
            "files_read",
            "acp_run",
        ],
        roots=[root],
    )
    pending = [
        p
        for p in service._proposals.values()
        if p.get("device_id") == device_id and p.get("status") == "pending"
    ]
    assert len(pending) == 1
    proposal_id = pending[0]["proposal_id"]
    result = await service.resolve_grant_proposal(
        device_id, proposal_id, accept=False, owner=owner
    )
    assert result["status"] == "rejected"
    fresh = service.repos.device_repo.get(device_id)
    assert fresh is not None
    assert "acp_run" not in fresh.permissions


@pytest.mark.asyncio
async def test_owner_http_resolve_may_accept_non_high_risk(rig: Any) -> None:
    """Non-high-risk pending proposals may still be accepted by owner HTTP."""
    service, owner, _, tmp = rig
    share = tmp / "share"
    share.mkdir()
    root = {
        "id": "shared",
        "name": "Shared",
        "path": str(share),
        "read": True,
        "write": True,
    }
    item = enroll(service, owner, permissions=[], roots=[root])
    device_id = item["device"]["device_id"]
    # Force confirm mode so files_write goes through a proposal.
    service.repos.device_repo.update(device_id, remote_grant_mode="confirm")
    await service.create_grant_proposal(
        owner,
        device_id,
        permissions=["desktop_view", "desktop_control", "files_read", "files_write"],
        roots=[root],
    )
    pending = [
        p
        for p in service._proposals.values()
        if p.get("device_id") == device_id and p.get("status") == "pending"
    ]
    assert len(pending) == 1
    proposal_id = pending[0]["proposal_id"]
    updated = await service.resolve_grant_proposal(
        device_id, proposal_id, accept=True, owner=owner
    )
    assert "files_write" in updated["permissions"]
    assert "command_exec" not in updated["permissions"]

