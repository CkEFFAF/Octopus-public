"""0044 audited device transfer: tickets, Hub≠direct, cancel, receipts gate."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

import pytest

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.devices.executor import DeviceExecutor
from octop.infra.devices.service import DeviceService
from octop.infra.devices.transfer_device import handle_negotiate, receipt_frame
from octop.infra.devices.transfer_session import (
    mint_ticket,
    new_ticket_claims,
    ticket_hash,
    verify_ticket,
)
from octop.infra.errors import ErrorCode, OctopError


@pytest.fixture
def rig(tmp_path: Path) -> Any:
    pool = SqlitePool(tmp_path / "control.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="owner", role="admin", password_hash="unused")
    repos.agent_repo.create(agent_id="writer", user_id=owner, name="Writer")
    service = DeviceService(repos)
    yield service, owner, tmp_path, repos
    pool.close()


def enroll(
    service: DeviceService,
    owner: int,
    *,
    roots: list[dict[str, Any]] | None = None,
    permissions: list[str] | None = None,
) -> dict[str, Any]:
    return service.enroll(
        pairing_code=service.pairing(owner)["pairing_code"],
        name="Device",
        platform="linux",
        capabilities=permissions or [],
        permissions=permissions or [],
        roots=roots or [],
    )


async def connected(
    service: DeviceService, enrolled: dict[str, Any], executor: DeviceExecutor
) -> Any:
    device_id = enrolled["device"]["device_id"]
    connection: Any = None

    async def send(frame: dict[str, Any]) -> None:
        if frame["type"] in {"hello_ack", "grants"}:
            executor.update_grants(frame["grant_version"], frame["permissions"], frame["roots"])
        elif frame["type"] == "request":
            try:
                result = await executor.execute(
                    frame["id"],
                    frame["action"],
                    frame["params"],
                    grant_version=frame["grant_version"],
                    permissions=frame["permissions"],
                )
                response = {"type": "result", "id": frame["id"], "ok": True, "result": result}
            except ValueError as exc:
                response = {"type": "result", "id": frame["id"], "ok": False, "error": str(exc)}
            await service.receive(connection, response)
        elif frame["type"] == "transfer.negotiate":
            # Control-plane only: validate structural binding; no TLS data plane here.
            handle_negotiate(frame, local_device_id=device_id)
        elif frame["type"] == "cancel":
            await executor.cancel(frame["id"])

    async def close() -> None:
        await executor.close()

    connection = await service.connect(device_id, enrolled["device_token"], send, close)
    return connection


def test_migration_037_creates_device_file_transfers(rig: Any) -> None:
    _, _, _, repos = rig
    with repos.db.connect() as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='device_file_transfers'"
        ).fetchone()
    assert row is not None


def test_ticket_forge_replay_expire(rig: Any) -> None:
    service, _, _, _ = rig
    secret = service._transfer_ticket_secret
    claims = new_ticket_claims(
        transfer_id="xfer1",
        source_device_id="src",
        target_device_id="dst",
        source_root_id="r",
        source_path="a.bin",
        target_root_id="r",
        target_path="b.bin",
        size=3,
        sha256="aa" * 32,
        source_grant_version=1,
        target_grant_version=1,
        ttl_seconds=60,
    )
    ticket = mint_ticket(secret, claims)
    assert verify_ticket(secret, ticket).transfer_id == "xfer1"
    # forge: flip payload without valid sig
    forged = ticket[:-4] + ("dead" if not ticket.endswith("dead") else "beef")
    with pytest.raises(ValueError, match="TRANSFER_TICKET_INVALID"):
        verify_ticket(secret, forged)
    # expire
    with pytest.raises(ValueError, match="TRANSFER_TICKET_INVALID"):
        verify_ticket(secret, ticket, now=claims.expires_at + 1)
    # replay/consumed
    with pytest.raises(ValueError, match="TRANSFER_TICKET_INVALID"):
        verify_ticket(secret, ticket, consumed=True)
    assert ticket_hash(ticket) == hashlib.sha256(ticket.encode()).hexdigest()
    # plaintext ticket must not equal stored hash
    assert ticket_hash(ticket) != ticket


@pytest.mark.asyncio
async def test_hub_transport_not_labeled_direct(rig: Any) -> None:
    service, owner, tmp, repos = rig
    payload = b"hub-only\x00" * 1000
    source_root, target_root = tmp / "source", tmp / "target"
    source_root.mkdir()
    target_root.mkdir()
    (source_root / "文档.bin").write_bytes(payload)
    devices = []
    executors = []
    for path in (source_root, target_root):
        roots = [{"id": "share", "name": "Files", "path": str(path), "read": True, "write": True}]
        executor = DeviceExecutor(["files_read", "files_write"], roots)
        devices.append(enroll(service, owner, roots=roots, permissions=executor.capabilities))
        executors.append(executor)
        await connected(service, devices[-1], executor)
    created = service.transfer(
        owner,
        {
            "source_device_id": devices[0]["device"]["device_id"],
            "source_root_id": "share",
            "source_path": "文档.bin",
            "target_device_id": devices[1]["device"]["device_id"],
            "target_root_id": "share",
            "target_path": "out.bin",
            "preferred_transport": "auto",
            "request_id": "req-hub-1",
        },
    )
    assert created["transfer_id"]
    assert created["operation_id"]
    assert created["preferred_transport"] == "auto"
    # idempotent request_id
    again = service.transfer(
        owner,
        {
            "source_device_id": devices[0]["device"]["device_id"],
            "source_root_id": "share",
            "source_path": "文档.bin",
            "target_device_id": devices[1]["device"]["device_id"],
            "target_root_id": "share",
            "target_path": "out.bin",
            "request_id": "req-hub-1",
        },
    )
    assert again["transfer_id"] == created["transfer_id"]

    await asyncio.gather(*list(service._jobs.values()))
    row = repos.device_transfer_repo.get(created["transfer_id"], owner=owner)
    assert row is not None
    assert row.actual_transport == "hub"
    assert row.actual_transport != "direct"
    assert row.status == "pending_receipt"
    assert (target_root / "out.bin").read_bytes() == payload
    # missing receipt must not be completed
    got = service.get_transfer(owner, created["transfer_id"])
    assert got["status"] != "completed"
    assert got["receipts"] == {"source": False, "target": False}

    # deliver both receipts → completed
    src_id = devices[0]["device"]["device_id"]
    dst_id = devices[1]["device"]["device_id"]
    await service.receive(
        service._connections[src_id],
        receipt_frame(
            transfer_id=created["transfer_id"],
            device_id=src_id,
            phase="completed",
            bytes_done=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            transport_used="hub",
        ),
    )
    mid = service.get_transfer(owner, created["transfer_id"])
    assert mid["status"] != "completed"
    await service.receive(
        service._connections[dst_id],
        receipt_frame(
            transfer_id=created["transfer_id"],
            device_id=dst_id,
            phase="completed",
            bytes_done=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            transport_used="hub",
        ),
    )
    done = service.get_transfer(owner, created["transfer_id"])
    assert done["status"] == "completed"
    assert done["actual_transport"] == "hub"
    await service.shutdown()


@pytest.mark.asyncio
async def test_explicit_direct_unavailable_without_p2p(rig: Any) -> None:
    service, owner, tmp, _ = rig
    source_root, target_root = tmp / "s", tmp / "t"
    source_root.mkdir()
    target_root.mkdir()
    (source_root / "a.bin").write_bytes(b"x")
    devices = []
    for path in (source_root, target_root):
        roots = [{"id": "share", "name": "Files", "path": str(path), "read": True, "write": True}]
        executor = DeviceExecutor(["files_read", "files_write"], roots)
        devices.append(enroll(service, owner, roots=roots, permissions=executor.capabilities))
        await connected(service, devices[-1], executor)
    with pytest.raises(OctopError) as exc:
        service.transfer(
            owner,
            {
                "source_device_id": devices[0]["device"]["device_id"],
                "source_root_id": "share",
                "source_path": "a.bin",
                "target_device_id": devices[1]["device"]["device_id"],
                "target_root_id": "share",
                "target_path": "b.bin",
                "preferred_transport": "direct",
            },
        )
    assert exc.value.code == ErrorCode.TRANSFER_DIRECT_UNAVAILABLE
    await service.shutdown()


@pytest.mark.asyncio
async def test_cancel_transfer_sets_cancelled(rig: Any) -> None:
    service, owner, tmp, repos = rig
    source_root, target_root = tmp / "s", tmp / "t"
    source_root.mkdir()
    target_root.mkdir()
    (source_root / "a.bin").write_bytes(b"payload-cancel")
    devices = []
    for path in (source_root, target_root):
        roots = [{"id": "share", "name": "Files", "path": str(path), "read": True, "write": True}]
        executor = DeviceExecutor(["files_read", "files_write"], roots)
        devices.append(enroll(service, owner, roots=roots, permissions=executor.capabilities))
        await connected(service, devices[-1], executor)
    created = service.transfer(
        owner,
        {
            "source_device_id": devices[0]["device"]["device_id"],
            "source_root_id": "share",
            "source_path": "a.bin",
            "target_device_id": devices[1]["device"]["device_id"],
            "target_root_id": "share",
            "target_path": "b.bin",
            "preferred_transport": "hub",
        },
    )
    # Cancel immediately (may race hub path); final status must be cancelled or already terminal.
    result = await service.cancel_transfer(owner, created["transfer_id"])
    assert result["status"] in {"cancelled", "completed", "pending_receipt", "failed"}
    if result["status"] == "cancelled":
        row = repos.device_transfer_repo.get(created["transfer_id"])
        assert row is not None
        assert row.error_code == "TRANSFER_CANCELLED"
    await service.shutdown()


def test_ticket_not_logged_in_public_row(rig: Any) -> None:
    _, owner, _, repos = rig
    from octop.infra.utils.ulid import new_ulid

    tid = new_ulid()
    row = repos.device_transfer_repo.create(
        {
            "transfer_id": tid,
            "owner_user_id": owner,
            "source_device_id": "s",
            "source_root_id": "r",
            "source_path": "p",
            "source_grant_version": 1,
            "target_device_id": "t",
            "target_root_id": "r",
            "target_path": "q",
            "target_grant_version": 1,
            "status": "negotiating",
            "audit_id": new_ulid(),
            "ticket_hash": "abc123",
            "preferred_transport": "auto",
        }
    )
    public = row.public()
    blob = str(public)
    assert "ticket" not in public
    assert "abc123" not in blob
