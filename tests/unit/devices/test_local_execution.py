"""The controller OS is an explicit, authenticated execution target."""

from __future__ import annotations

import base64
import sys
from pathlib import Path
from typing import Any

import pytest

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.devices.service import DeviceService
from octop.infra.errors import OctopError
from octop.infra.execution.service import ExecutionService


@pytest.fixture
async def local(tmp_path: Path) -> Any:
    pool = SqlitePool(tmp_path / "hub.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="owner", role="admin", password_hash="unused")
    other = repos.user_repo.create(username="other", role="user", password_hash="unused")
    repos.agent_repo.create(agent_id="expert", user_id=owner, name="Expert")
    repos.thread_repo.insert(
        thread_id="thread",
        agent_id="expert",
        user_id=owner,
        channel_type="dashboard",
        session_key="test",
    )
    devices = DeviceService(repos, local_state_dir=tmp_path / "runtime")
    yield ExecutionService(devices), owner, other, tmp_path
    await devices.shutdown()
    pool.close()


async def test_local_is_explicit_and_uses_native_operations(local: Any) -> None:
    service, owner, _, root = local
    with pytest.raises(OctopError, match="choose an execution device"):
        service.resolve(owner, agent_id="expert")
    assert not service.devices.local_execution._runtimes
    context = service.resolve(
        owner, target_kind="local", working_dir=str(root), agent_id="expert", thread_id="thread"
    )
    assert context.device_id is None and context.target_kind == "local"
    await service.call(
        owner,
        context.context_id,
        "fs.write",
        {
            "path": "native.txt",
            "data_b64": base64.b64encode(b"local project").decode(),
            "create_only": True,
        },
    )
    assert (root / "native.txt").read_bytes() == b"local project"
    value = await service.call(
        owner,
        context.context_id,
        "command.run",
        {
            "argv": [
                sys.executable,
                "-c",
                "from pathlib import Path; print(Path('native.txt').read_text())",
            ],
            "timeout": 10,
        },
    )
    assert value["status"] == "completed" and "local project" in value["result"]["stdout"]
    frozen = service.for_run(
        owner, context.context_id, agent_id="expert", thread_id="thread", run_id="run"
    )
    assert frozen.target_kind == "local" and frozen.device_id is None
    assert service.target(owner, frozen.context_id)["target_kind"] == "local"


async def test_local_role_owner_and_mode_are_checked_on_every_operation(local: Any) -> None:
    service, owner, other, root = local
    with pytest.raises(OctopError, match="administrator"):
        service.resolve(other, target_kind="local")
    with pytest.raises(OctopError, match="cannot also select"):
        service.resolve(owner, target_kind="local", device_id="other-device")
    context = service.resolve(owner, target_kind="local", working_dir=str(root))
    with pytest.raises(OctopError, match="not found"):
        await service.call(other, context.context_id, "fs.list", {})
    plan = service.resolve(owner, target_kind="local", work_mode="plan", working_dir=str(root))
    assert (await service.call(owner, plan.context_id, "fs.list", {}))["result"]["path"] == str(
        root
    )
    with pytest.raises(OctopError, match="only permits observation"):
        await service.call(owner, plan.context_id, "command.run", {"argv": [sys.executable, "-V"]})
    service.devices.repos.user_repo.set_role(owner, "user")
    with pytest.raises(OctopError, match="administrator"):
        await service.call(owner, context.context_id, "fs.list", {})


async def test_local_default_session_precedence_and_migration_replay(local: Any) -> None:
    service, owner, _, root = local
    service.save_default_target(owner, None, str(root), "local")
    context = service.resolve(owner, agent_id="expert", thread_id="thread")
    assert context.source == "account_default" and context.target_kind == "local"
    service.save_selection(
        owner, "thread", {"target_kind": "local", "device_id": None, "work_mode": "debug"}
    )
    run_migrations(service.devices.repos.db)
    selected = ExecutionService(service.devices).resolve(
        owner, agent_id="expert", thread_id="thread"
    )
    assert selected.target_kind == "local" and selected.source == "session_selection"
    assert selected.work_mode == "debug"
    # An explicit bad remote selection never falls back to this local default.
    with pytest.raises(OctopError):
        service.resolve(owner, device_id="offline-or-deleted")
    assert service.get(owner, context.context_id).target_kind == "local"


async def test_local_browser_backend_revalidates_context_and_derives_lane(
    local: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import json
    from dataclasses import replace

    service, owner, _, root = local
    context = service.resolve(
        owner, target_kind="local", working_dir=str(root), agent_id="expert", thread_id="thread"
    )
    backend = service.local_backend(owner)
    runtime = backend.runtime(owner)
    received: list[dict[str, Any]] = []

    async def browser_reply(
        operation: str, action: str, params: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        received.append(params)
        return {"text": "PRIVATE_DOM_BODY"}

    monkeypatch.setattr(runtime, "execute", browser_reply)
    response = await service.call(
        owner, context.context_id, "browser.observe", {"browser_lane": "forged"}
    )
    assert response["result"]["text"] == "PRIVATE_DOM_BODY"
    assert (
        received[0]["browser_lane"]
        == hashlib.sha256(json.dumps([owner, "expert", "thread"]).encode()).hexdigest()
    )
    with pytest.raises(OctopError, match="not found"):
        await backend.call(
            replace(context, context_id="unpersisted"), "test", "browser.observe", {}
        )
    plan = service.resolve(owner, target_kind="local", work_mode="plan")
    with pytest.raises(OctopError, match="only permits observation"):
        await backend.call(replace(plan, work_mode="agentic"), "test", "browser.action", {})
    assert len(received) == 1
    service.devices.repos.user_repo.set_role(owner, "user")
    with pytest.raises(OctopError, match="administrator"):
        await backend.call(context, "test", "browser.observe", {})
