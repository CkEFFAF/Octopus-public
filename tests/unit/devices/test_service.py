"""Control center, executor and authenticated device dispatch integration."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

import pytest
from langgraph.config import var_child_runnable_config

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.devices.executor import DeviceExecutor
from octop.infra.devices.service import DeviceService
from octop.infra.devices.tools import build_device_tools
from octop.infra.errors import ErrorCode, OctopError


@pytest.fixture
def rig(tmp_path: Path) -> Any:
    pool = SqlitePool(tmp_path / "control.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="owner", role="admin", password_hash="unused")
    other = repos.user_repo.create(username="other", role="user", password_hash="unused")
    repos.agent_repo.create(agent_id="writer", user_id=owner, name="Writer")
    service = DeviceService(repos)
    yield service, owner, other, tmp_path
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
        platform="windows",
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
        elif frame["type"] == "cancel":
            await executor.cancel(frame["id"])

    async def close() -> None:
        await executor.close()

    connection = await service.connect(device_id, enrolled["device_token"], send, close)
    return connection


def test_pairing_single_use_and_account_binding(rig: Any) -> None:
    service, owner, other, _ = rig
    code = service.pairing(owner)["pairing_code"]
    first = service.enroll(
        pairing_code=code, name="PC", platform="windows", capabilities=[], permissions=[], roots=[]
    )
    with pytest.raises(OctopError):
        service.enroll(
            pairing_code=code,
            name="Copy",
            platform="windows",
            capabilities=[],
            permissions=[],
            roots=[],
        )
    second = enroll(service, owner)
    assert first["device"]["device_id"] != second["device"]["device_id"]
    assert service.list_devices(other) == []
    with pytest.raises(OctopError) as exc:
        service.owned(other, first["device"]["device_id"])
    assert exc.value.code == ErrorCode.NOT_FOUND
    assert "token_hash" not in str(service.list_devices(owner))


@pytest.mark.asyncio
async def test_two_device_file_transfer_checksum_and_ledger(rig: Any) -> None:
    service, owner, _, tmp = rig
    payload = b"devices integration\n" * 72000
    source_root, target_root = tmp / "source", tmp / "target"
    source_root.mkdir()
    target_root.mkdir()
    (source_root / "input.txt").write_bytes(payload)
    executors = []
    devices = []
    for path in (source_root, target_root):
        roots = [{"id": "share", "name": "Files", "path": str(path), "read": True, "write": True}]
        executor = DeviceExecutor(["files_read", "files_write"], roots)
        devices.append(enroll(service, owner, roots=roots, permissions=executor.capabilities))
        executors.append(executor)
        await connected(service, devices[-1], executor)
    op = service.transfer(
        owner,
        {
            "source_device_id": devices[0]["device"]["device_id"],
            "source_root_id": "share",
            "source_path": "input.txt",
            "target_device_id": devices[1]["device"]["device_id"],
            "target_root_id": "share",
            "target_path": "output.txt",
        },
    )
    await asyncio.gather(*list(service._jobs.values()))
    result = service.operation(owner, op["operation_id"])
    assert result.status == "completed", result.error
    assert (target_root / "output.txt").read_bytes() == payload
    assert result.result["sha256"] == hashlib.sha256(payload).hexdigest()
    assert result.result["bytes_done"] == len(payload)
    assert "data_b64" not in str(result.public())
    await service.shutdown()


@pytest.mark.asyncio
async def test_permission_revoke_blocks_token_and_increase(rig: Any) -> None:
    service, owner, _, _ = rig
    item = enroll(service, owner, permissions=["desktop_view", "desktop_control"])
    device_id = item["device"]["device_id"]
    with pytest.raises(OctopError):
        await service.update(owner, device_id, permissions=["command_exec"])
    await service.update(owner, device_id, permissions=["desktop_view"])
    with pytest.raises(OctopError):
        await service.update(owner, device_id, permissions=["desktop_view", "desktop_control"])
    await service.revoke(owner, device_id)
    with pytest.raises(OctopError):
        service.authenticate(device_id, item["device_token"])
    assert service.list_devices(owner)[0]["revoked_at"] is not None


@pytest.mark.asyncio
async def test_command_requires_human_and_cancels_on_grant_change(rig: Any) -> None:
    service, owner, _, tmp = rig
    root = {"id": "share", "name": "Share", "path": str(tmp), "read": True, "write": False}
    executor = DeviceExecutor(["command_exec"], [root], command_enabled=True)
    item = enroll(service, owner, roots=[root], permissions=["command_exec"])
    device_id = item["device"]["device_id"]
    await connected(service, item, executor)
    with pytest.raises(OctopError):
        await service.call(
            owner, device_id, "command.run", {"root_id": "share", "argv": ["unused"]}
        )
    op = service.submit(owner, device_id, "command.run", {"root_id": "share", "argv": ["unused"]})
    assert op["status"] == "pending_confirmation"
    await service.update(owner, device_id, permissions=[])
    assert service.operation(owner, op["operation_id"]).status == "cancelled"
    with pytest.raises(OctopError):
        service.confirm(owner, op["operation_id"])
    await service.shutdown()


@pytest.mark.asyncio
async def test_agent_target_cannot_override_or_cross_account(rig: Any) -> None:
    service, owner, other, _ = rig
    first, second = enroll(service, owner), enroll(service, owner)
    await connected(service, first, DeviceExecutor([], []))
    await connected(service, second, DeviceExecutor([], []))
    tools = {t.name: t for t in build_device_tools(service, "writer")}
    token = var_child_runnable_config.set(
        {
            "configurable": {
                "user": str(owner),
                "octop_device_target": {
                    "device_id": first["device"]["device_id"],
                    "grant_version": 1,
                },
            }
        }
    )
    try:
        response = await tools["device_call"].ainvoke(
            {"device_id": second["device"]["device_id"], "action": "status", "params": {}}
        )
        assert '"code": "FORBIDDEN"' in response
    finally:
        var_child_runnable_config.reset(token)
    with pytest.raises(OctopError):
        service.submit(other, first["device"]["device_id"], "ping", {})
    await service.shutdown()


@pytest.mark.asyncio
async def test_disconnect_unknown_no_automatic_replay_and_reconcile(rig: Any) -> None:
    service, owner, _, _ = rig
    item = enroll(service, owner)
    frames: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        frames.append(frame)

    async def close() -> None:
        pass

    connection = await service.connect(
        item["device"]["device_id"], item["device_token"], send, close
    )
    op = service.submit(owner, connection.device_id, "ping", {})
    await asyncio.sleep(0)
    service.disconnect(connection)
    await asyncio.gather(*list(service._jobs.values()))
    assert service.operation(owner, op["operation_id"]).status == "unknown"
    restored = await service.connect(connection.device_id, item["device_token"], send, close)
    assert sum(frame["type"] == "request" for frame in frames) == 1
    await service.receive(
        restored,
        {
            "type": "reconcile",
            "results": [{"id": op["operation_id"], "ok": True, "result": {"ok": True}}],
        },
    )
    assert service.operation(owner, op["operation_id"]).status == "completed"
    await service.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [None, 1, 600, 3600])
async def test_confirmed_command_waits_for_its_execution_deadline(
    rig: Any, monkeypatch: pytest.MonkeyPatch, timeout: int | None
) -> None:
    service, owner, _, tmp = rig
    root = {"id": "share", "name": "Share", "path": str(tmp), "read": True, "write": False}
    item = enroll(service, owner, roots=[root], permissions=["command_exec"])
    executor = DeviceExecutor(["command_exec"], [root], command_enabled=True)
    await connected(service, item, executor)
    waits: list[float] = []
    original_wait = asyncio.wait_for

    async def observe_wait(awaitable: Any, duration: float) -> Any:
        waits.append(duration)
        return await original_wait(awaitable, duration)

    monkeypatch.setattr(asyncio, "wait_for", observe_wait)
    # No long sleep: the missing executable fails immediately, while the host's
    # chosen deadline is observable at the protocol boundary.
    params: dict[str, Any] = {"root_id": "share", "argv": ["octopus-test-missing-command"]}
    if timeout is not None:
        params["timeout"] = timeout
    op = service.submit(owner, item["device"]["device_id"], "command.run", params)
    service.confirm(owner, op["operation_id"])
    await asyncio.gather(*list(service._jobs.values()))
    assert len(waits) == 1
    assert waits[0] >= (60 if timeout is None else timeout) + 5
    assert service.operation(owner, op["operation_id"]).status == "failed"
    await service.shutdown()


@pytest.mark.parametrize("timeout", [0, 3601, True, None, "600", 1.5])
def test_invalid_command_deadline_is_rejected_before_enqueue(rig: Any, timeout: Any) -> None:
    service, owner, _, _ = rig
    item = enroll(service, owner, permissions=["command_exec"])
    with pytest.raises(OctopError, match="timeout"):
        service.submit(
            owner,
            item["device"]["device_id"],
            "command.run",
            {"root_id": "share", "argv": ["unused"], "timeout": timeout},
        )
    assert service.repos.device_repo.list_operations(owner) == []
