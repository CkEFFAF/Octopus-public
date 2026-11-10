from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from octop.infra.devices.executor import DeviceExecutionError, DeviceExecutor


@pytest.mark.parametrize("action", ["jobs.status", "jobs.list", "jobs.logs"])
async def test_job_observations_do_not_rewrite_operation_journal(tmp_path, monkeypatch, action):
    executor = DeviceExecutor(
        ["command_exec", "files_read"],
        [],
        trust_mode="owner",
        working_dir=str(tmp_path),
        state_dir=tmp_path / "state",
    )
    operation = AsyncMock(side_effect=[{"status": "running"}, {"status": "completed"}])
    monkeypatch.setattr(executor, "_execute", operation)
    kwargs = {"grant_version": 0, "permissions": ["command_exec", "files_read"]}
    assert await executor.execute("query", action, {}, **kwargs) == {"status": "running"}
    assert await executor.execute("query", action, {}, **kwargs) == {"status": "completed"}
    assert not (tmp_path / "state" / "operations.json").exists()
    assert not executor._journal
    assert not executor._active


async def test_observation_still_checks_current_permissions(tmp_path, monkeypatch):
    executor = DeviceExecutor(
        ["command_exec", "files_read"],
        [],
        trust_mode="owner",
        working_dir=str(tmp_path),
        state_dir=tmp_path / "state",
    )
    operation = AsyncMock(return_value={})
    monkeypatch.setattr(executor, "_execute", operation)
    with pytest.raises(DeviceExecutionError):
        await executor.execute("query", "jobs.status", {}, grant_version=0, permissions=[])
    operation.assert_not_called()


async def test_job_mutations_keep_durable_idempotency(tmp_path, monkeypatch):
    executor = DeviceExecutor(
        ["command_exec", "files_read"],
        [],
        trust_mode="owner",
        working_dir=str(tmp_path),
        state_dir=tmp_path / "state",
    )
    operation = AsyncMock(return_value={"job_id": "accepted"})
    monkeypatch.setattr(executor, "_execute", operation)
    kwargs = {"grant_version": 0, "permissions": ["command_exec", "files_read"]}
    first = await executor.execute("submit", "jobs.start", {}, **kwargs)
    assert await executor.execute("submit", "jobs.start", {}, **kwargs) == first
    operation.assert_awaited_once()
    assert (tmp_path / "state" / "operations.json").exists()
    with pytest.raises(DeviceExecutionError, match="reused"):
        await executor.execute("submit", "jobs.status", {}, **kwargs)
