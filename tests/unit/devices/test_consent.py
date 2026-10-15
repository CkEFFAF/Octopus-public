from __future__ import annotations

import asyncio
import time

import pytest

from octop.infra.devices import consent
from octop.infra.devices.executor import DeviceExecutionError, DeviceExecutor


@pytest.mark.parametrize("expiry", [None, float("nan"), float("inf"), 0, "later"])
async def test_invalid_or_expired_request_never_prompts(tmp_path, expiry):
    assert not await consent.confirm(
        tmp_path,
        request_id="invalid",
        server_url="https://trusted.test",
        details="desktop",
        expires_at=expiry,
    )
    assert not (tmp_path / "consents").exists()


@pytest.mark.parametrize("accept", [True, False])
async def test_device_local_inbox_decision_and_cleanup(tmp_path, monkeypatch, accept):
    # Use the actual inbox path without opening native windows on CI hosts.
    monkeypatch.setattr(consent, "_native_confirm", lambda *_: time.sleep(1) or False)
    task = asyncio.create_task(
        consent.confirm(
            tmp_path,
            request_id="../../remote-id",
            server_url="https://trusted.test",
            details="/data/workspace",
            expires_at=time.time() + 3,
        )
    )
    for _ in range(100):
        if consent.pending_consents(tmp_path):
            break
        await asyncio.sleep(0.01)
    pending = consent.pending_consents(tmp_path)
    assert len(pending) == 1
    assert pending[0]["details"].startswith("https://trusted.test")
    consent.decide_consent(tmp_path, "../../remote-id", accept=accept)
    assert await task is accept
    assert not consent.pending_consents(tmp_path)
    assert not list((tmp_path / "consents").iterdir())


def test_new_root_requires_local_approval_and_validates_atomically(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    executor = DeviceExecutor(["files_read"], [])
    desired = {"id": "workspace", "path": str(root), "read": True, "write": True}
    with pytest.raises(DeviceExecutionError, match="ROOT_NOT_ALLOWED"):
        executor.apply_grant_proposal(["files_read"], [desired])
    with pytest.raises(DeviceExecutionError, match="existing directory"):
        executor.apply_grant_proposal(
            ["files_read"],
            [desired, {**desired, "id": "bad", "path": str(root / "missing")}],
            allow_new_roots=True,
        )
    assert not executor.local_roots
    executor.apply_grant_proposal(["files_read"], [desired], allow_new_roots=True)
    assert executor.local_roots["workspace"]["write"]


def test_confirmation_displays_all_paths_without_silent_truncation():
    details = "first-path\n" + "long-path" * 1000 + "\nlast-sensitive-path"
    assert "last-sensitive-path" in consent._text(details)
    assert "\\u202e" in consent._text("requester\u202e")


async def test_native_unavailable_retains_inbox_for_local_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(consent, "_native_confirm", lambda *_: None)
    task = asyncio.create_task(
        consent.confirm(
            tmp_path,
            request_id="headless",
            server_url="https://trusted.test",
            details="permissions",
            expires_at=time.time() + 3,
        )
    )
    await asyncio.sleep(0.3)
    assert not task.done()
    assert consent.pending_consents(tmp_path)[0]["request_id"] == "headless"
    consent.decide_consent(tmp_path, "headless", accept=True)
    assert await task


@pytest.mark.parametrize("profile", ["default", "secondary"])
@pytest.mark.parametrize("action", ["files.read", "files.list", "files.write_begin"])
async def test_broad_trust_zone_cannot_read_or_forge_device_approvals(tmp_path, profile, action):
    state_root = tmp_path / "state"
    state = state_root if profile == "default" else state_root / "controllers" / "profile"
    root = {"id": "home", "path": str(tmp_path), "read": True, "write": True}
    executor = DeviceExecutor(["files_read", "files_write"], [root], state_dir=state)
    inbox = state / "consents"
    inbox.mkdir()
    (inbox / "request.json").write_text('{"nonce":"private"}')
    relative = (inbox / "request.json").relative_to(tmp_path).as_posix()
    if action == "files.list":
        relative = inbox.relative_to(tmp_path).as_posix()
    # Both own controller and other controller states are outside file grants.
    for path in [relative, "state/device.json"]:
        with pytest.raises(DeviceExecutionError, match="private"):
            await executor.execute(
                action + path,
                action,
                {"root_id": "home", "path": path},
                grant_version=executor.grant_version,
                permissions=["files_read", "files_write"],
            )
    await executor.close()
