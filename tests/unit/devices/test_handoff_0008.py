"""0008 MVP-S1: Dashboard desktop target switch + Allow takeover."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
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
    service: DeviceService, owner: int, *, permissions: list[str] | None = None
) -> dict[str, Any]:
    caps = [
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
        permissions=permissions
        if permissions is not None
        else ["desktop_view", "desktop_control", "files_read"],
        roots=[],
    )


async def connect(
    service: DeviceService,
    enrolled: dict[str, Any],
    *,
    auto_accept: bool | None = True,
) -> Any:
    """Connect device; auto_accept=True/False resolves takeover; None leaves pending."""
    device_id = enrolled["device"]["device_id"]
    connection: Any = None
    frames: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        frames.append(frame)
        if frame.get("type") == "desktop_takeover" and auto_accept is not None:
            await service.receive(
                connection,
                {
                    "type": "desktop_takeover_resolve",
                    "request_id": frame["request_id"],
                    "decision": "accept" if auto_accept else "reject",
                },
            )

    async def close() -> None:
        return None

    connection = await service.connect(
        device_id,
        enrolled["device_token"],
        send,
        close,
        client_protocol_version=2,
    )
    connection.frames = frames
    return connection


@pytest.mark.asyncio
async def test_ac001_accept_switches_target(rig: Any) -> None:
    service, owner, _, _ = rig
    a = enroll(service, owner)
    b = enroll(service, owner)
    await connect(service, a, auto_accept=True)
    await connect(service, b, auto_accept=True)
    # Seed current target A without going through switch (direct for setup).
    service._desktop_targets[owner] = a["device"]["device_id"]
    result = await service.request_desktop_switch(owner, b["device"]["device_id"], mode="view")
    assert result["status"] == "accepted"
    assert service.get_desktop_target(owner)["device_id"] == b["device"]["device_id"]
    events = service.list_takeover_events(owner)
    assert events and events[0]["outcome"] == "accepted"


@pytest.mark.asyncio
async def test_ac002_reject_keeps_previous(rig: Any) -> None:
    service, owner, _, _ = rig
    a = enroll(service, owner)
    b = enroll(service, owner)
    await connect(service, a, auto_accept=True)
    await connect(service, b, auto_accept=False)
    service._desktop_targets[owner] = a["device"]["device_id"]
    result = await service.request_desktop_switch(owner, b["device"]["device_id"])
    assert result["status"] == "rejected"
    assert service.get_desktop_target(owner)["device_id"] == a["device"]["device_id"]
    assert service.list_takeover_events(owner)[0]["outcome"] == "rejected"


@pytest.mark.asyncio
async def test_ac002_timeout_keeps_previous(rig: Any) -> None:
    service, owner, _, _ = rig
    a = enroll(service, owner)
    b = enroll(service, owner)
    await connect(service, a, auto_accept=True)
    await connect(service, b, auto_accept=None)  # leave pending
    service._desktop_targets[owner] = a["device"]["device_id"]
    result = await service.request_desktop_switch(owner, b["device"]["device_id"])
    assert result["status"] == "pending"
    request_id = result["request_id"]
    # Expire
    service._takeovers[request_id]["expires_at"] = 0
    polled = service.get_takeover_request(owner, request_id)
    assert polled["status"] == "timeout"
    assert service.get_desktop_target(owner)["device_id"] == a["device"]["device_id"]
    assert any(e["outcome"] == "timeout" for e in service.list_takeover_events(owner))


@pytest.mark.asyncio
async def test_ac003_missing_desktop_view_forbidden(rig: Any) -> None:
    service, owner, _, _ = rig
    a = enroll(service, owner)
    b = enroll(service, owner)
    # Strip desktop grants after enroll (REQ-007 would otherwise re-add defaults).
    service.repos.device_repo.update(b["device"]["device_id"], permissions=["files_read"])
    await connect(service, a, auto_accept=True)
    await connect(service, b, auto_accept=True)
    service._desktop_targets[owner] = a["device"]["device_id"]
    with pytest.raises(OctopError) as exc:
        await service.request_desktop_switch(owner, b["device"]["device_id"])
    assert exc.value.code == ErrorCode.FORBIDDEN
    assert "DESKTOP_PERMISSION_REQUIRED" in str(exc.value)
    assert service.get_desktop_target(owner)["device_id"] == a["device"]["device_id"]


@pytest.mark.asyncio
async def test_ac005_takeover_does_not_expand_high_risk(rig: Any) -> None:
    service, owner, _, _ = rig
    b = enroll(service, owner, permissions=["desktop_view", "desktop_control", "files_read"])
    await connect(service, b, auto_accept=True)
    await service.request_desktop_switch(owner, b["device"]["device_id"], mode="view_control")
    row = service.repos.device_repo.get(b["device"]["device_id"])
    assert row is not None
    assert "command_exec" not in row.permissions
    assert "acp_run" not in row.permissions
    assert "files_write" not in row.permissions


@pytest.mark.asyncio
async def test_ac010_non_owner_forbidden(rig: Any) -> None:
    service, owner, other, _ = rig
    item = enroll(service, owner)
    await connect(service, item, auto_accept=True)
    with pytest.raises(OctopError) as exc:
        await service.request_desktop_switch(other, item["device"]["device_id"])
    assert exc.value.code == ErrorCode.FORBIDDEN


@pytest.mark.asyncio
async def test_ac011_events_recorded(rig: Any) -> None:
    service, owner, _, _ = rig
    a = enroll(service, owner)
    b = enroll(service, owner)
    await connect(service, a, auto_accept=True)
    await connect(service, b, auto_accept=True)
    await service.request_desktop_switch(owner, a["device"]["device_id"])
    await service.request_desktop_switch(owner, b["device"]["device_id"])
    events = service.list_takeover_events(owner)
    assert len(events) >= 2
    assert {e["outcome"] for e in events} >= {"accepted"}


@pytest.mark.asyncio
async def test_same_target_noop_accepted(rig: Any) -> None:
    service, owner, _, _ = rig
    a = enroll(service, owner)
    await connect(service, a, auto_accept=True)
    service._desktop_targets[owner] = a["device"]["device_id"]
    result = await service.request_desktop_switch(owner, a["device"]["device_id"])
    assert result["status"] == "accepted"
    assert result["request_id"] is None


@pytest.mark.asyncio
async def test_desktop_target_note_independent_of_binding(rig: Any) -> None:
    service, owner, _, _ = rig
    state = service.get_desktop_target(owner)
    assert state["note"] == "desktop_target_independent_of_expert_binding"
    assert state["device_id"] is None
