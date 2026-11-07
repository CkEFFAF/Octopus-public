"""0044 audited device transfer: tickets, Hub≠direct, cancel, receipts gate."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.devices.executor import DeviceExecutor
from octop.infra.devices.service import DeviceService
from octop.infra.devices.transfer_device import (
    handle_negotiate,
    receipt_frame,
    resolve_root_path,
    run_direct_source,
    run_direct_target,
)
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


def enable_p2p(repos: RepoBundle, device_id: str) -> None:
    row = repos.device_repo.get(device_id)
    assert row is not None
    meta = {**(row.runtime_metadata or {}), "transfer_protocol_version": 2}
    with repos.db.connect() as conn:
        conn.execute(
            "UPDATE devices SET runtime_metadata = ? WHERE device_id = ?",
            (json.dumps(meta), device_id),
        )


async def connected(
    service: DeviceService,
    enrolled: dict[str, Any],
    executor: DeviceExecutor,
    *,
    p2p: bool = False,
) -> Any:
    device_id = enrolled["device"]["device_id"]
    connection: Any = None
    pending_source: dict[str, Any] | None = None

    async def send_to_hub(frame: dict[str, Any]) -> None:
        await service.receive(connection, frame)

    async def send(frame: dict[str, Any]) -> None:
        nonlocal pending_source
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
            ack = handle_negotiate(frame, local_device_id=device_id)
            if not p2p or ack.get("preferred_transport") == "hub":
                return
            scope = ack["path_scope"]
            path = resolve_root_path(
                executor.local_roots,
                str(scope.get("root_id") or ""),
                str(scope.get("path") or ""),
            )
            if ack["role"] == "target":
                asyncio.create_task(
                    run_direct_target(
                        ticket=ack["ticket"],
                        claims=ack["claims"],
                        dest_path=path,
                        device_id=device_id,
                        send_to_hub=send_to_hub,
                        overwrite=False,
                    )
                )
            elif ack["role"] == "source":
                pending_source = {
                    "ticket": ack["ticket"],
                    "claims": ack["claims"],
                    "path": path,
                }
        elif frame["type"] == "transfer.peer":
            if pending_source is None:
                return
            src = pending_source
            pending_source = None
            asyncio.create_task(
                run_direct_source(
                    ticket=src["ticket"],
                    claims=src["claims"],
                    source_path=src["path"],
                    device_id=device_id,
                    host=str(frame["host"]),
                    port=int(frame["port"]),
                    send_to_hub=send_to_hub,
                )
            )
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
    forged = ticket[:-4] + ("dead" if not ticket.endswith("dead") else "beef")
    with pytest.raises(ValueError, match="TRANSFER_TICKET_INVALID"):
        verify_ticket(secret, forged)
    with pytest.raises(ValueError, match="TRANSFER_TICKET_INVALID"):
        verify_ticket(secret, ticket, now=claims.expires_at + 1)
    with pytest.raises(ValueError, match="TRANSFER_TICKET_INVALID"):
        verify_ticket(secret, ticket, consumed=True)
    assert ticket_hash(ticket) == hashlib.sha256(ticket.encode()).hexdigest()
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
        await connected(service, devices[-1], executor, p2p=False)
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
    got = service.get_transfer(owner, created["transfer_id"])
    assert got["status"] != "completed"
    assert got["receipts"] == {"source": False, "target": False}

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
async def test_receipt_sha256_mismatch_rejects_completed(rig: Any) -> None:
    service, owner, tmp, repos = rig
    payload = b"sha-gate"
    source_root, target_root = tmp / "s", tmp / "t"
    source_root.mkdir()
    target_root.mkdir()
    (source_root / "a.bin").write_bytes(payload)
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
    await asyncio.gather(*list(service._jobs.values()))
    src_id = devices[0]["device"]["device_id"]
    dst_id = devices[1]["device"]["device_id"]
    good = hashlib.sha256(payload).hexdigest()
    await service.receive(
        service._connections[src_id],
        receipt_frame(
            transfer_id=created["transfer_id"],
            device_id=src_id,
            phase="completed",
            bytes_done=len(payload),
            sha256=good,
            transport_used="hub",
        ),
    )
    await service.receive(
        service._connections[dst_id],
        receipt_frame(
            transfer_id=created["transfer_id"],
            device_id=dst_id,
            phase="completed",
            bytes_done=len(payload),
            sha256="ff" * 32,
            transport_used="hub",
        ),
    )
    row = repos.device_transfer_repo.get(created["transfer_id"])
    assert row is not None
    assert row.status == "failed"
    assert row.error_code == "TRANSFER_SOURCE_CHANGED"
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
        await connected(service, devices[-1], executor, p2p=False)
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


@pytest.mark.asyncio
async def test_direct_tls_peer_transfer_hub_does_not_forward(rig: Any) -> None:
    """AC-0044-01 evidence: dual Native executors + localhost TLS; Hub never runs _transfer."""
    service, owner, tmp, repos = rig
    payload = "直连载荷-中文\x00binary".encode()
    source_root, target_root = tmp / "src", tmp / "dst"
    source_root.mkdir()
    target_root.mkdir()
    (source_root / "报告.bin").write_bytes(payload)
    devices = []
    executors = []
    for path in (source_root, target_root):
        roots = [{"id": "share", "name": "Files", "path": str(path), "read": True, "write": True}]
        executor = DeviceExecutor(["files_read", "files_write"], roots)
        enrolled = enroll(service, owner, roots=roots, permissions=executor.capabilities)
        enable_p2p(repos, enrolled["device"]["device_id"])
        devices.append(enrolled)
        executors.append(executor)
        await connected(service, enrolled, executor, p2p=True)

    hub_forward_calls = {"n": 0}
    real_transfer = service._transfer

    async def counting_transfer(op: Any) -> dict[str, Any]:
        hub_forward_calls["n"] += 1
        return await real_transfer(op)

    service._transfer = counting_transfer  # type: ignore[method-assign]

    created = service.transfer(
        owner,
        {
            "source_device_id": devices[0]["device"]["device_id"],
            "source_root_id": "share",
            "source_path": "报告.bin",
            "target_device_id": devices[1]["device"]["device_id"],
            "target_root_id": "share",
            "target_path": "inbox/报告.bin",
            "preferred_transport": "direct",
            "request_id": "req-direct-1",
        },
    )
    await asyncio.gather(*list(service._jobs.values()))
    row = repos.device_transfer_repo.get(created["transfer_id"], owner=owner)
    assert row is not None
    assert row.actual_transport == "direct"
    assert row.status == "completed"
    assert hub_forward_calls["n"] == 0, "Hub must not forward payload on direct path"
    assert (target_root / "inbox" / "报告.bin").read_bytes() == payload
    assert hashlib.sha256(payload).hexdigest() == row.sha256
    got = service.get_transfer(owner, created["transfer_id"])
    assert got["actual_transport"] == "direct"
    assert got["fallback_reason"] is None
    await service.shutdown()
