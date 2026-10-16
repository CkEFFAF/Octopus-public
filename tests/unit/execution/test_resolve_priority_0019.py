"""0019 S0: lock ExecutionService.resolve priority chain (no list fallback)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.devices.executor import DeviceExecutor
from octop.infra.devices.service import DeviceService
from octop.infra.errors import OctopError
from octop.infra.execution.service import ExecutionService


@pytest.fixture
def fleet(tmp_path: Path) -> Any:
    pool = SqlitePool(tmp_path / "hub.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="owner", role="admin", password_hash="unused")
    yield DeviceService(repos), owner, tmp_path
    pool.close()


async def attach(service: DeviceService, owner: int, directory: Path) -> Any:
    directory.mkdir()
    executor = DeviceExecutor(
        [], [], trust_mode="owner", working_dir=str(directory), state_dir=directory / "state"
    )
    enrolled = service.enroll(
        owner_user_id=owner,
        name=directory.name,
        platform="windows" if sys.platform == "win32" else "linux",
        capabilities=executor.capabilities,
        permissions=executor.capabilities,
        roots=[],
        trust_mode="owner",
    )
    device_id = enrolled["device"]["device_id"]
    connection: Any = None

    async def send(frame: dict[str, Any]) -> None:
        if frame["type"] in {"hello_ack", "grants"}:
            executor.apply_policy(
                frame["trust_mode"], frame["permissions"], frame.get("working_dir")
            )
            executor.update_grants(frame["grant_version"], frame["permissions"], frame["roots"])
            if connection is not None:
                row = service.owned(owner, device_id)
                await service.receive(
                    connection,
                    {
                        "type": "policy_applied",
                        "policy_revision": row.policy_revision,
                        "trust_mode": row.trust_mode,
                        "runtime": {"working_dir": str(executor.working_dir), "os_user": "u"},
                    },
                )
        elif frame["type"] == "request":
            value = await executor.execute(
                frame["id"],
                frame["action"],
                frame["params"],
                grant_version=frame["grant_version"],
                permissions=frame["permissions"],
            )
            await service.receive(
                connection, {"type": "result", "id": frame["id"], "ok": True, "result": value}
            )

    async def close() -> None:
        await executor.close()

    connection = await service.connect(
        device_id, enrolled["device_token"], send, close, client_protocol_version=3
    )
    return enrolled, executor, connection


@pytest.mark.asyncio
async def test_resolve_priority_explicit_session_expert_account_then_force_choose(
    fleet: Any,
) -> None:
    service, owner, tmp = fleet
    service.repos.agent_repo.create(agent_id="expert", user_id=owner, name="Expert")
    service.repos.thread_repo.insert(
        thread_id="thread",
        user_id=owner,
        agent_id="expert",
        channel_type="dashboard",
        session_key="test",
    )
    one, ex_one, c_one = await attach(service, owner, tmp / "one")
    two, ex_two, c_two = await attach(service, owner, tmp / "two")
    first, second = one["device"]["device_id"], two["device"]["device_id"]
    executions = ExecutionService(service)
    try:
        with pytest.raises(OctopError, match="choose an execution device"):
            executions.resolve(owner, agent_id="expert")

        # Never silently pick devices[0] — account default must be explicit.
        listed = [d.device_id for d in service.repos.device_repo.list_for_owner(owner)]
        assert first in listed and second in listed

        executions.save_default_target(owner, first, "/account")
        assert executions.resolve(owner, agent_id="expert").source == "account_default"

        expert = executions.resolve(
            owner, agent_id="expert", binding={"device_id": second, "working_dir": "/expert"}
        )
        assert (expert.device_id, expert.source) == (second, "expert_default")

        executions.save_selection(
            owner, "thread", {"device_id": first, "working_dir": "/session", "work_mode": "agentic"}
        )
        session = executions.resolve(
            owner,
            agent_id="expert",
            thread_id="thread",
            binding={"device_id": second, "working_dir": "/expert"},
        )
        assert (session.device_id, session.source) == (first, "session_selection")
        # Expert binding unchanged in DB.
        cfg = json.loads(service.repos.agent_repo.get("expert").config_json or "{}")
        assert (
            "device_binding" not in cfg or cfg.get("device_binding", {}).get("device_id") != first
        )

        explicit = executions.resolve(
            owner, agent_id="expert", thread_id="thread", device_id=second
        )
        assert explicit.device_id == second and explicit.source == "session_selection"
    finally:
        service.disconnect(c_one)
        service.disconnect(c_two)
        await ex_one.close()
        await ex_two.close()
