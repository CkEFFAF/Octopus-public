"""AC-04/07: device grants and operation settlement gate task completion."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.devices.service import DeviceService
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.task_board.models import BoardAction, Review
from octop.infra.task_board.service import TaskBoardService


@pytest_asyncio.fixture
async def board_device_rig(tmp_path: Path) -> AsyncIterator[Any]:
    pool = SqlitePool(tmp_path / "board-device-lifecycle.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="owner", role="admin", password_hash="test")
    repos.agent_repo.create(agent_id="writer", user_id=owner, name="Writer")
    devices = DeviceService(repos)
    root = {"id": "share", "name": "Share", "path": str(tmp_path), "read": True, "write": False}
    enrolled = devices.enroll(
        pairing_code=devices.pairing(owner)["pairing_code"],
        name="Task device",
        platform="windows",
        capabilities=["command_exec"],
        permissions=["command_exec"],
        roots=[root],
    )
    requests: list[dict[str, Any]] = []
    request_sent = asyncio.Event()

    async def send(frame: dict[str, Any]) -> None:
        if frame["type"] == "request":
            requests.append(frame)
            request_sent.set()

    async def close() -> None:
        return None

    device_id = enrolled["device"]["device_id"]
    connection = await devices.connect(device_id, enrolled["device_token"], send, close)
    harness = SimpleNamespace(
        config=SimpleNamespace(pick_default_model_ref=lambda: "test-model"),
        model_factory=SimpleNamespace(get=lambda _: object()),
        aget_history=AsyncMock(return_value=[]),
    )
    delivery = SimpleNamespace(
        deliver=AsyncMock(return_value="Reported result"), replace_repos=Mock()
    )
    board = TaskBoardService(
        repos=repos,
        timezone="Asia/Shanghai",
        registry=SimpleNamespace(get_agent=lambda _: harness),
        gateway=SimpleNamespace(
            thread_registry=SimpleNamespace(get_or_create_by_key=AsyncMock(return_value="thread"))
        ),
        delivery=delivery,
    )
    board.set_device_service(devices)
    try:
        yield SimpleNamespace(
            board=board,
            devices=devices,
            owner=owner,
            device_id=device_id,
            connection=connection,
            repos=repos,
            delivery=delivery,
            requests=requests,
            request_sent=request_sent,
        )
    finally:
        await board.shutdown()
        await devices.shutdown()
        pool.close()


async def action(rig: Any, kind: str, task_id: str = "", **payload: Any) -> Any:
    return await rig.board.action(
        rig.owner,
        BoardAction(
            revision=rig.board.snapshot(rig.owner).revision,
            action=kind,
            task_id=task_id,
            payload=payload,
        ),
    )


async def confirmed_task(rig: Any, **payload: Any) -> str:
    board = await action(
        rig,
        "create",
        title="Device task",
        agent_id="writer",
        device_id=rig.device_id,
        **payload,
    )
    task_id = board.tasks[-1].id
    await action(rig, "confirm", task_id)
    return str(task_id)


@pytest.mark.asyncio
async def test_repair_waits_for_human_confirmed_device_command_before_acceptance(
    board_device_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = board_device_rig
    repair_submitted = asyncio.Event()
    calls = 0

    async def deliver(command: Any) -> str:
        nonlocal calls
        calls += 1
        if calls == 2:
            rig.devices.submit(
                rig.owner,
                rig.device_id,
                "command.run",
                {"root_id": "share", "argv": ["unused"]},
                agent_id="writer",
                task_run_id=command.task_run_id,
            )
            repair_submitted.set()
        return "Agent reports completion"

    judgments = 0

    async def judge(**kwargs: Any) -> Review:
        nonlocal judgments
        judgments += 1
        passed = judgments == 2
        return Review(
            reviewer="independent",
            scores=[90 if passed else 30] * 3,
            evidence="Independent test verdict",
            passed=passed,
            created_at=kwargs["created_at"],
            run_id=kwargs["run"].id,
        )

    rig.delivery.deliver = deliver
    monkeypatch.setattr("octop.infra.task_board.service.judge", judge)
    task_id = await confirmed_task(rig, acceptance="automatic", auto_repair=True)
    await action(rig, "run", task_id, request_id="repair-run")
    jobs = list(rig.board._jobs.values())
    await asyncio.wait_for(repair_submitted.wait(), timeout=2)
    await asyncio.sleep(0)

    waiting = rig.board.snapshot(rig.owner).tasks[0]
    operations = rig.repos.device_repo.list_for_task_run(rig.owner, waiting.runs[-1].id)
    assert len(operations) == 1 and operations[0].status == "pending_confirmation"
    assert waiting.runs[-1].state == "running"
    assert waiting.status == "running"
    assert judgments == 1
    assert rig.requests == []  # Agent has no route to human confirmation.

    operation = rig.devices.confirm(rig.owner, operations[0].operation_id)
    await asyncio.wait_for(rig.request_sent.wait(), timeout=2)
    result = {"returncode": 0, "stdout": "done", "stderr": "", "truncated": False}
    await rig.devices.receive(
        rig.connection,
        {"type": "result", "id": operation["operation_id"], "ok": True, "result": result},
    )
    await asyncio.wait_for(asyncio.gather(*jobs), timeout=3)

    settled = rig.board.snapshot(rig.owner).tasks[0]
    assert settled.status == "done"
    assert settled.runs[-1].state == "succeeded"
    assert rig.devices.operation(rig.owner, operation["operation_id"]).status == "completed"
    assert judgments == 2


@pytest.mark.asyncio
async def test_failed_device_command_cannot_enter_model_acceptance(
    board_device_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = board_device_rig
    submitted = asyncio.Event()

    async def deliver(command: Any) -> str:
        rig.devices.submit(
            rig.owner,
            rig.device_id,
            "command.run",
            {"root_id": "share", "argv": ["unused"]},
            agent_id="writer",
            task_run_id=command.task_run_id,
        )
        submitted.set()
        return "Agent incorrectly claims success"

    rig.delivery.deliver = deliver
    judge = AsyncMock()
    monkeypatch.setattr("octop.infra.task_board.service.judge", judge)
    task_id = await confirmed_task(rig, acceptance="automatic")
    await action(rig, "run", task_id, request_id="failed-command-run")
    jobs = list(rig.board._jobs.values())
    await asyncio.wait_for(submitted.wait(), timeout=2)
    run_id = rig.board.snapshot(rig.owner).tasks[0].runs[-1].id
    operation = rig.repos.device_repo.list_for_task_run(rig.owner, run_id)[0]
    rig.devices.confirm(rig.owner, operation.operation_id)
    await asyncio.wait_for(rig.request_sent.wait(), timeout=2)
    await rig.devices.receive(
        rig.connection,
        {
            "type": "result",
            "id": operation.operation_id,
            "ok": True,
            "result": {"returncode": 1, "stdout": "", "stderr": "command failed"},
        },
    )
    await asyncio.wait_for(asyncio.gather(*jobs), timeout=3)

    assert rig.devices.operation(rig.owner, operation.operation_id).status == "failed"
    assert rig.board.snapshot(rig.owner).tasks[0].status == "failed"
    judge.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_device_waiting_task_returns_current_board_without_revision_conflict(
    board_device_rig: Any,
) -> None:
    rig = board_device_rig

    async def deliver(command: Any) -> str:
        rig.devices.submit(
            rig.owner,
            rig.device_id,
            "ping",
            {},
            agent_id="writer",
            task_run_id=command.task_run_id,
        )
        return "Await device result"

    rig.delivery.deliver = deliver
    task_id = await confirmed_task(rig)
    await action(rig, "run", task_id, request_id="cancel-run")
    await asyncio.wait_for(rig.request_sent.wait(), timeout=2)
    jobs = list(rig.board._jobs.values())

    cancelled = await action(rig, "cancel", task_id)
    await asyncio.gather(*jobs, return_exceptions=True)
    current = rig.board.snapshot(rig.owner)
    assert cancelled.revision == current.revision
    assert current.tasks[0].status == "failed"
    assert current.tasks[0].runs[-1].state == "interrupted"
    operations = rig.repos.device_repo.list_for_task_run(rig.owner, current.tasks[0].runs[-1].id)
    assert len(operations) == 1
    assert operations[0].status in {"cancelled", "unknown"}


@pytest.mark.asyncio
async def test_device_grant_version_change_requires_fresh_task_confirmation(
    board_device_rig: Any,
) -> None:
    rig = board_device_rig
    task_id = await confirmed_task(rig)
    original_pin = rig.board.snapshot(rig.owner).tasks[0].pin
    original_version = rig.devices.owned(rig.owner, rig.device_id).grant_version
    await rig.devices.update(rig.owner, rig.device_id, permissions=[])
    assert rig.devices.owned(rig.owner, rig.device_id).grant_version == original_version + 1

    with pytest.raises(OctopError) as denied:
        await action(rig, "run", task_id, request_id="stale-confirmation")
    assert denied.value.code == ErrorCode.TASK_BOARD_PIN_REQUIRED
    assert rig.delivery.deliver.await_count == 0
    assert rig.board.snapshot(rig.owner).tasks[0].runs == []

    await action(rig, "confirm", task_id)
    assert rig.board.snapshot(rig.owner).tasks[0].pin != original_pin
    await action(rig, "run", task_id, request_id="fresh-confirmation")
    await asyncio.gather(*list(rig.board._jobs.values()))
    assert rig.delivery.deliver.await_count == 1
    assert rig.board.snapshot(rig.owner).tasks[0].runs[-1].state == "succeeded"
