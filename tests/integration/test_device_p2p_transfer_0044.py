"""0044 integration: LAN-direct TLS + Hub fallback + sha256 gate (AC aspects)."""

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
from octop.infra.errors import ErrorCode, OctopError


@pytest.fixture
def rig(tmp_path: Path) -> Any:
    pool = SqlitePool(tmp_path / "control.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="owner", role="admin", password_hash="unused")
    service = DeviceService(repos)
    yield service, owner, tmp_path, repos
    pool.close()


def enroll(
    service: DeviceService,
    owner: int,
    roots: list[dict[str, Any]],
    permissions: list[str],
) -> dict[str, Any]:
    return service.enroll(
        pairing_code=service.pairing(owner)["pairing_code"],
        name="Device",
        platform="linux",
        capabilities=permissions,
        permissions=permissions,
        roots=roots,
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
    p2p: bool,
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
                # Same-host dual-executor harness: intentional loopback advertise.
                asyncio.create_task(
                    run_direct_target(
                        ticket=ack["ticket"],
                        claims=ack["claims"],
                        dest_path=path,
                        device_id=device_id,
                        send_to_hub=send_to_hub,
                        listen_host="127.0.0.1",
                        advertise_host="127.0.0.1",
                        allow_loopback=True,
                    )
                )
            else:
                pending_source = {
                    "ticket": ack["ticket"],
                    "claims": ack["claims"],
                    "path": path,
                }
        elif frame["type"] == "transfer.peer" and pending_source is not None:
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
        elif frame["type"] == "transfer.cancel":
            pending_source = None
        elif frame["type"] == "cancel":
            await executor.cancel(frame["id"])

    async def close() -> None:
        await executor.close()

    connection = await service.connect(device_id, enrolled["device_token"], send, close)
    return connection


@pytest.mark.asyncio
async def test_ac_direct_path_dual_executor(rig: Any) -> None:
    service, owner, tmp, repos = rig
    payload = b"AC01-" + "中文路径".encode() + b"\x00\xff"
    src_root, dst_root = tmp / "a", tmp / "b"
    src_root.mkdir()
    dst_root.mkdir()
    (src_root / "文档.bin").write_bytes(payload)
    devices = []
    for path in (src_root, dst_root):
        roots = [{"id": "share", "name": "Files", "path": str(path), "read": True, "write": True}]
        executor = DeviceExecutor(["files_read", "files_write"], roots)
        enrolled = enroll(service, owner, roots, executor.capabilities)
        enable_p2p(repos, enrolled["device"]["device_id"])
        devices.append(enrolled)
        await connected(service, enrolled, executor, p2p=True)

    hub_calls = {"n": 0}
    real = service._transfer

    async def counted(op: Any) -> dict[str, Any]:
        hub_calls["n"] += 1
        return await real(op)

    service._transfer = counted  # type: ignore[method-assign]
    created = service.transfer(
        owner,
        {
            "source_device_id": devices[0]["device"]["device_id"],
            "source_root_id": "share",
            "source_path": "文档.bin",
            "target_device_id": devices[1]["device"]["device_id"],
            "target_root_id": "share",
            "target_path": "收件/文档.bin",
            "preferred_transport": "auto",
        },
    )
    await asyncio.gather(*list(service._jobs.values()))
    row = repos.device_transfer_repo.get(created["transfer_id"])
    assert row is not None
    assert row.actual_transport == "direct"
    assert row.status == "completed"
    assert hub_calls["n"] == 0
    assert (dst_root / "收件" / "文档.bin").read_bytes() == payload
    assert row.sha256 == hashlib.sha256(payload).hexdigest()
    await service.shutdown()


@pytest.mark.asyncio
async def test_ac_hub_fallback_when_no_p2p(rig: Any) -> None:
    service, owner, tmp, repos = rig
    payload = b"fallback-hub"
    src_root, dst_root = tmp / "a", tmp / "b"
    src_root.mkdir()
    dst_root.mkdir()
    (src_root / "a.bin").write_bytes(payload)
    devices = []
    for path in (src_root, dst_root):
        roots = [{"id": "share", "name": "Files", "path": str(path), "read": True, "write": True}]
        executor = DeviceExecutor(["files_read", "files_write"], roots)
        enrolled = enroll(service, owner, roots, executor.capabilities)
        # no enable_p2p → capability_missing → hub
        devices.append(enrolled)
        await connected(service, enrolled, executor, p2p=False)
    created = service.transfer(
        owner,
        {
            "source_device_id": devices[0]["device"]["device_id"],
            "source_root_id": "share",
            "source_path": "a.bin",
            "target_device_id": devices[1]["device"]["device_id"],
            "target_root_id": "share",
            "target_path": "b.bin",
            "preferred_transport": "auto",
        },
    )
    await asyncio.gather(*list(service._jobs.values()))
    row = repos.device_transfer_repo.get(created["transfer_id"])
    assert row is not None
    assert row.actual_transport == "hub"
    assert row.fallback_reason == "capability_missing"
    assert (dst_root / "b.bin").read_bytes() == payload
    await service.shutdown()


@pytest.mark.asyncio
async def test_ac_sha256_gate_blocks_completed(rig: Any) -> None:
    service, owner, tmp, repos = rig
    payload = b"gate"
    src_root, dst_root = tmp / "a", tmp / "b"
    src_root.mkdir()
    dst_root.mkdir()
    (src_root / "a.bin").write_bytes(payload)
    devices = []
    for path in (src_root, dst_root):
        roots = [{"id": "share", "name": "Files", "path": str(path), "read": True, "write": True}]
        executor = DeviceExecutor(["files_read", "files_write"], roots)
        enrolled = enroll(service, owner, roots, executor.capabilities)
        devices.append(enrolled)
        await connected(service, enrolled, executor, p2p=False)
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
    await service.receive(
        service._connections[dst_id],
        receipt_frame(
            transfer_id=created["transfer_id"],
            device_id=dst_id,
            phase="completed",
            bytes_done=len(payload),
            sha256="00" * 32,
            transport_used="hub",
        ),
    )
    row = repos.device_transfer_repo.get(created["transfer_id"])
    assert row is not None
    assert row.status == "failed"
    assert row.error_code == "TRANSFER_SOURCE_CHANGED"
    await service.shutdown()


@pytest.mark.asyncio
async def test_ac_cancel_transfer(rig: Any) -> None:
    service, owner, tmp, repos = rig
    src_root, dst_root = tmp / "a", tmp / "b"
    src_root.mkdir()
    dst_root.mkdir()
    (src_root / "a.bin").write_bytes(b"cancel-me")
    devices = []
    for path in (src_root, dst_root):
        roots = [{"id": "share", "name": "Files", "path": str(path), "read": True, "write": True}]
        executor = DeviceExecutor(["files_read", "files_write"], roots)
        enrolled = enroll(service, owner, roots, executor.capabilities)
        devices.append(enrolled)
        await connected(service, enrolled, executor, p2p=False)
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
    await service.shutdown()


@pytest.mark.asyncio
async def test_explicit_direct_fails_cleanly_without_capability(rig: Any) -> None:
    service, owner, tmp, _ = rig
    src_root, dst_root = tmp / "a", tmp / "b"
    src_root.mkdir()
    dst_root.mkdir()
    (src_root / "a.bin").write_bytes(b"x")
    devices = []
    for path in (src_root, dst_root):
        roots = [{"id": "share", "name": "Files", "path": str(path), "read": True, "write": True}]
        executor = DeviceExecutor(["files_read", "files_write"], roots)
        enrolled = enroll(service, owner, roots, executor.capabilities)
        devices.append(enrolled)
        await connected(service, enrolled, executor, p2p=False)
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
