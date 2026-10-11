"""Task ledger behavior: ownership, execution gates, dependencies and recovery."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest
from langchain_core.messages import AIMessage
from langgraph.config import var_child_runnable_config

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.task_board.models import BoardAction, Schedule
from octop.infra.task_board.service import TaskBoardService, next_fire
from octop.infra.task_board.tools import build_task_board_tools


@pytest.fixture
def rig(tmp_path: Path) -> Any:
    pool = SqlitePool(tmp_path / "tasks.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    uid = repos.user_repo.create(username="task-owner", password_hash="test", role="admin")
    other = repos.user_repo.create(username="other", password_hash="test", role="user")
    repos.agent_repo.create(agent_id="writer", user_id=uid, name="Writer")
    repos.agent_repo.create(agent_id="reviewer", user_id=uid, name="Reviewer")
    repos.agent_repo.create(agent_id="foreign", user_id=other, name="Foreign")
    registry = Mock()
    gateway = SimpleNamespace(
        thread_registry=SimpleNamespace(get_or_create_by_key=AsyncMock(return_value="real-thread"))
    )
    delivery = SimpleNamespace(
        deliver=AsyncMock(return_value="Completed with evidence"), replace_repos=Mock()
    )
    service = TaskBoardService(
        repos=repos, timezone="Asia/Shanghai", registry=registry, gateway=gateway, delivery=delivery
    )
    return SimpleNamespace(
        service=service, uid=uid, other=other, repos=repos, delivery=delivery, pool=pool
    )


async def action(rig: Any, operation: str, task_id: str = "", **payload: Any) -> Any:
    command = BoardAction.model_validate(
        {
            "action": operation,
            "task_id": task_id,
            "revision": rig.service.snapshot(rig.uid).revision,
            "payload": payload,
        }
    )
    return await rig.service.action(rig.uid, command)


async def create(rig: Any, **payload: Any) -> str:
    board = await action(rig, "create", title="Do work", agent_id="writer", **payload)
    return str(board.tasks[-1].id)


async def finish(rig: Any, task_id: str) -> None:
    await action(rig, "confirm", task_id)
    await action(rig, "run", task_id, request_id=task_id)
    await asyncio.gather(*rig.service._jobs.values())


async def accept(rig: Any, task_id: str, scores: list[int] | None = None) -> Any:
    return await action(
        rig,
        "review",
        task_id,
        scores=scores or [88, 84, 86],
        evidence="Reviewed files and tests independently",
    )


@pytest.mark.asyncio
async def test_owner_isolation_revision_and_archive(rig: Any) -> None:
    task_id = await create(rig, tags=[" Design ", "Design"])
    board = rig.service.snapshot(rig.uid)
    assert board.tasks[0].tags == ["Design"]
    assert rig.service.snapshot(rig.other).tasks == []
    with pytest.raises(OctopError) as conflict:
        await rig.service.action(
            rig.uid, BoardAction(revision=0, action="archive", task_id=task_id)
        )
    assert conflict.value.code == ErrorCode.TASK_BOARD_CONFLICT
    with pytest.raises(OctopError):
        await action(rig, "handover", task_id, agent_id="foreign")
    await action(rig, "archive", task_id)
    with pytest.raises(OctopError):
        await action(rig, "update", task_id, title="Changed")
    await action(rig, "restore", task_id)
    assert not rig.service.snapshot(rig.uid).tasks[0].archived
    # Reconstructing the service reads the same database, not browser memory.
    assert rig.repos.task_board_repo.get(rig.uid)[0] == rig.service.snapshot(rig.uid).revision


@pytest.mark.asyncio
async def test_tools_use_authenticated_harness_user_for_reads_and_mutations(rig: Any) -> None:
    task_id = await create(rig)
    tools = {tool.name: tool for tool in build_task_board_tools(rig.service)}
    # The gateway sends configurable.user, not user_id. Ignore a conflicting alias.
    token = var_child_runnable_config.set(
        {"configurable": {"user": str(rig.uid), "user_id": rig.other, "agent_id": "writer"}}
    )
    try:
        listed = json.loads(await tools["task_board_list"].ainvoke({}))
        assert [task["id"] for task in listed["tasks"]] == [task_id]
        fetched = json.loads(await tools["task_board_get"].ainvoke({"task_id": task_id}))
        assert fetched["title"] == "Do work"
        await tools["task_board_update"].ainvoke(
            {"task_id": task_id, "changes": {"progress": "Tool update"}}
        )
        created = json.loads(await tools["task_board_create"].ainvoke({"title": "Tool draft"}))
        assert len(created["tasks"]) == 2
        assert rig.service.snapshot(rig.uid).tasks[0].progress == "Tool update"
        assert rig.service.snapshot(rig.other).tasks == []
        assert rig.service.snapshot(0).tasks == []
    finally:
        var_child_runnable_config.reset(token)

    token = var_child_runnable_config.set({"configurable": {"user": str(rig.other)}})
    try:
        assert json.loads(await tools["task_board_list"].ainvoke({}))["tasks"] == []
        assert "error" in json.loads(await tools["task_board_get"].ainvoke({"task_id": task_id}))
    finally:
        var_child_runnable_config.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [{}, {"user_id": 1}, {"user": "0"}, {"user": "-1"}])
async def test_tools_reject_missing_or_invalid_authenticated_user(rig: Any, config: Any) -> None:
    tools = {tool.name: tool for tool in build_task_board_tools(rig.service)}
    token = var_child_runnable_config.set({"configurable": config})
    try:
        with pytest.raises(ValueError):
            await tools["task_board_list"].ainvoke({})
        assert "error" in json.loads(await tools["task_board_create"].ainvoke({"title": "Denied"}))
        assert rig.repos.task_board_repo.user_ids() == []
    finally:
        var_child_runnable_config.reset(token)


@pytest.mark.asyncio
async def test_pin_changes_and_human_gate(rig: Any) -> None:
    task_id = await create(rig)
    with pytest.raises(OctopError) as error:
        await action(rig, "run", task_id)
    assert error.value.code == ErrorCode.TASK_BOARD_PIN_REQUIRED
    command = BoardAction(
        revision=rig.service.snapshot(rig.uid).revision, action="confirm", task_id=task_id
    )
    with pytest.raises(OctopError):
        await rig.service.action(rig.uid, command, human=False)
    await action(rig, "confirm", task_id)
    rig.repos.agent_repo.update_config("writer", config_json='{"tools_disabled":[]}')
    with pytest.raises(OctopError) as error:
        await action(rig, "run", task_id)
    assert error.value.code == ErrorCode.TASK_BOARD_PIN_REQUIRED
    board = await action(
        rig,
        "handover",
        task_id,
        agent_id="reviewer",
        goal="Goal",
        progress="Progress",
        next_step="Next",
    )
    assert not board.tasks[0].pin
    assert board.tasks[0].handovers[0].from_agent == "writer"


@pytest.mark.asyncio
async def test_run_reuses_delivery_and_independent_acceptance(rig: Any) -> None:
    task_id = await create(rig)
    await finish(rig, task_id)
    task = rig.service.snapshot(rig.uid).tasks[0]
    assert task.status == "running" and task.review is None
    assert task.runs[0].output == "Completed with evidence"
    assert task.runs[0].thread_id == "real-thread"
    assert rig.delivery.deliver.await_count == 1
    await action(rig, "run", task_id, request_id=task_id)
    assert rig.delivery.deliver.await_count == 1
    command = BoardAction(
        revision=rig.service.snapshot(rig.uid).revision,
        action="review",
        task_id=task_id,
        payload={"scores": [99, 99, 99], "evidence": "Self review"},
    )
    with pytest.raises(OctopError):
        await rig.service.action(rig.uid, command, human=False)
    rejected = await accept(rig, task_id, [99, 64, 99])
    assert rejected.tasks[0].status == "failed"
    approved = await accept(rig, task_id)
    assert approved.tasks[0].status == "done"
    assert approved.tasks[0].runs[0].review.passed


@pytest.mark.asyncio
async def test_changed_contract_requires_fresh_run_and_preserves_old_report(rig: Any) -> None:
    task_id = await create(rig)
    await finish(rig, task_id)
    await accept(rig, task_id)
    changed = await action(rig, "update", task_id, prompt="A different deliverable")
    assert changed.tasks[0].status == "todo"
    assert changed.tasks[0].review is None
    assert changed.tasks[0].runs[-1].review.passed
    with pytest.raises(OctopError):
        await accept(rig, task_id)
    with pytest.raises(OctopError):
        await action(rig, "run", task_id, request_id="unconfirmed-contract")
    await action(rig, "confirm", task_id)
    await action(rig, "run", task_id, request_id="fresh-contract")
    await asyncio.gather(*rig.service._jobs.values())
    accepted = await accept(rig, task_id)
    assert accepted.tasks[0].status == "done"
    assert len(accepted.tasks[0].runs) == 2


@pytest.mark.asyncio
async def test_global_permission_change_invalidates_confirmation(rig: Any) -> None:
    task_id = await create(rig)
    await action(rig, "confirm", task_id)
    rig.repos.settings_repo.set("security_policy", '{"mode":"new-policy"}')
    with pytest.raises(OctopError) as error:
        await action(rig, "run", task_id)
    assert error.value.code == ErrorCode.TASK_BOARD_PIN_REQUIRED


@pytest.mark.asyncio
async def test_parent_completion_and_cycles(rig: Any) -> None:
    parent = await create(rig)
    child = await create(rig, parent_id=parent)
    with pytest.raises(OctopError):
        await action(rig, "parent", parent, parent_id=child)
    await finish(rig, parent)
    await accept(rig, parent)
    assert rig.service.snapshot(rig.uid).tasks[0].status == "running"
    await finish(rig, child)
    await accept(rig, child)
    assert [task.status for task in rig.service.snapshot(rig.uid).tasks] == ["done", "done"]
    # New unfinished child invalidates parent completion immediately.
    await create(rig, parent_id=parent)
    assert rig.service.snapshot(rig.uid).tasks[0].status == "running"
    await action(rig, "archive", parent)
    with pytest.raises(OctopError):
        await create(rig, parent_id=parent)
    await action(rig, "restore", parent)


@pytest.mark.asyncio
async def test_cancel_and_restart_never_resend(rig: Any) -> None:
    rig.delivery.deliver = AsyncMock(side_effect=lambda _: asyncio.sleep(600))
    # A blocked executor allows a restart to interrupt an in-flight run.
    waiting = asyncio.Event()

    async def deliver(_: Any) -> str:
        await waiting.wait()
        return "done"

    rig.delivery.deliver = AsyncMock(side_effect=deliver)
    task_id = await create(rig)
    await action(rig, "confirm", task_id)
    await action(rig, "run", task_id)
    await asyncio.sleep(0)
    rig.service.recover()
    assert rig.service.snapshot(rig.uid).tasks[0].runs[-1].state == "interrupted"
    await rig.service.shutdown()
    assert rig.delivery.deliver.await_count == 1


def test_cron_timezone_and_invalid_rules() -> None:
    now = datetime(2026, 10, 8, 0, 0, tzinfo=ZoneInfo("UTC"))
    rule = Schedule(cron="0 9 * * *", timezone="Asia/Shanghai")
    assert next_fire(rule, now) == "2026-10-08T09:00:00+08:00"
    for cron, zone in [("* * * * * *", "UTC"), ("0 25 * * *", "UTC"), ("0 9 * * *", "bad/zone")]:
        with pytest.raises(OctopError):
            next_fire(Schedule(cron=cron, timezone=zone), now)


@pytest.mark.asyncio
async def test_schedule_persists_claims_and_skips_busy(rig: Any) -> None:
    task_id = await create(rig)
    await action(rig, "confirm", task_id)
    await action(rig, "schedule", task_id, cron="* * * * *", timezone="Asia/Shanghai")
    board = rig.service.snapshot(rig.uid)
    board.tasks[0].schedule.next_run = "2020-01-01T00:00:00+08:00"
    rig.service._save(rig.uid, board)
    await rig.service.tick()
    await asyncio.gather(*rig.service._jobs.values())
    await rig.service.tick()
    assert rig.delivery.deliver.await_count == 1
    task = rig.service.snapshot(rig.uid).tasks[0]
    assert task.schedule.last_trigger == "2020-01-01T00:00:00+08:00"
    assert task.schedule.next_run > task.schedule.last_trigger


@pytest.mark.asyncio
async def test_tree_preflight_is_atomic_and_parent_waits(rig: Any) -> None:
    parent = await create(rig)
    child = await create(rig, parent_id=parent)
    await action(rig, "confirm", parent)
    before = rig.service.snapshot(rig.uid)
    with pytest.raises(OctopError):
        await action(rig, "run", parent, cascade=True, request_id="tree")
    after = rig.service.snapshot(rig.uid)
    assert after.revision == before.revision
    assert all(not task.runs for task in after.tasks)
    await action(rig, "confirm", parent, cascade=True)
    await action(rig, "run", parent, cascade=True, request_id="tree")
    await asyncio.gather(*rig.service._jobs.values())
    assert rig.delivery.deliver.await_count == 2
    await accept(rig, parent)
    assert rig.service.snapshot(rig.uid).tasks[0].status == "running"
    await accept(rig, child)
    assert all(task.status == "done" for task in rig.service.snapshot(rig.uid).tasks)
    await action(rig, "run", parent, cascade=True, request_id="tree")
    assert rig.delivery.deliver.await_count == 2


@pytest.mark.asyncio
async def test_tag_rename_includes_archive_and_frozen_prefix(rig: Any) -> None:
    first = await create(rig, tags=["docs"])
    second = await create(rig, tags=["docs"])
    await action(rig, "archive", second)
    await action(rig, "tags", name="docs", rename="documentation", prefix="Write in Chinese.")
    board = rig.service.snapshot(rig.uid)
    assert all(task.tags == ["documentation"] for task in board.tasks)
    assert board.tag_prefixes == {"documentation": "Write in Chinese."}
    await finish(rig, first)
    assert rig.delivery.deliver.call_args.args[0].prompt.startswith("Write in Chinese.")
    await accept(rig, first)
    await action(rig, "tags", name="documentation", prefix="Write in English.")
    assert not rig.service.snapshot(rig.uid).tasks[0].pin
    with pytest.raises(OctopError):
        await accept(rig, first)
    await action(rig, "tags", name="documentation", rename="")
    assert all(not task.tags for task in rig.service.snapshot(rig.uid).tasks)


def fake_judge(rig: Any, scores: list[int]) -> AsyncMock:
    messages = []
    for score in scores:
        messages.extend(
            [
                AIMessage(
                    content=json.dumps(
                        {"score_a": score, "score_b": 10, "evidence": "Observable output checked"}
                    ),
                    usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
                ),
                AIMessage(
                    content=json.dumps(
                        {"score_a": 10, "score_b": score, "evidence": "Swapped result checked"}
                    ),
                    usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
                ),
            ]
        )
    llm = SimpleNamespace(ainvoke=AsyncMock(side_effect=messages))
    harness = SimpleNamespace(
        model_factory=SimpleNamespace(get=Mock(return_value=llm)),
        config=SimpleNamespace(pick_default_model_ref=lambda: "provider/judge"),
        aget_history=AsyncMock(
            return_value=[AIMessage(content="file evidence password=hidden-secret")]
        ),
    )
    rig.service._registry.get_agent.return_value = harness
    return llm.ainvoke


@pytest.mark.asyncio
async def test_automatic_acceptance_swapped_rounds_usage_redaction(rig: Any) -> None:
    calls = fake_judge(rig, [90, 85, 80])
    task_id = await create(rig, acceptance="automatic")
    await finish(rig, task_id)
    task = rig.service.snapshot(rig.uid).tasks[0]
    assert task.status == "done"
    assert task.review.scores == [90, 85, 80]
    assert task.review.baseline_scores == [10, 10, 10]
    assert len(task.review.rounds) == 6
    assert task.review.usage["model_calls"] == 6
    assert calls.await_count == 6
    sent = calls.call_args_list[0].args[0][1].content
    assert "hidden-secret" not in sent
    assert "[REDACTED]" in sent


@pytest.mark.asyncio
async def test_one_low_criterion_rejects_and_anomaly_holds(rig: Any) -> None:
    calls = fake_judge(rig, [95, 64, 95])
    task_id = await create(rig, acceptance="automatic")
    await finish(rig, task_id)
    task = rig.service.snapshot(rig.uid).tasks[0]
    assert task.status == "failed"
    assert not task.review.passed
    calls.side_effect = TimeoutError("judge timeout")
    await action(rig, "run", task_id, request_id="anomaly")
    await asyncio.gather(*rig.service._jobs.values())
    task = rig.service.snapshot(rig.uid).tasks[0]
    assert task.status == "running"
    assert task.review is None
    assert task.runs[-1].acceptance_error == "judge timeout"
    before = rig.delivery.deliver.await_count
    fake_judge(rig, [90, 90, 90])
    await action(rig, "verify", task_id)
    await asyncio.gather(*rig.service._jobs.values())
    assert rig.delivery.deliver.await_count == before
    assert rig.service.snapshot(rig.uid).tasks[0].status == "done"


def test_restricted_dom_dow_are_unix_alternatives() -> None:
    now = datetime(2026, 10, 8, 0, 0, tzinfo=ZoneInfo("UTC"))
    rule = Schedule(cron="0 9 1 * mon", timezone="UTC")
    assert next_fire(rule, now) == "2026-10-12T09:00:00+00:00"


@pytest.mark.asyncio
async def test_automatic_repair_is_bounded_and_reverifies(rig: Any) -> None:
    calls = fake_judge(rig, [50, 50, 50, 90, 90, 90])
    task_id = await create(rig, acceptance="automatic", auto_repair=True)
    await finish(rig, task_id)
    task = rig.service.snapshot(rig.uid).tasks[0]
    assert task.status == "done"
    assert len(task.runs[-1].attempts) == 2
    assert rig.delivery.deliver.await_count == 2
    assert calls.await_count == 12
    assert "Independent reviewer issues" in rig.delivery.deliver.call_args.args[0].prompt


def test_json_and_bearer_credentials_are_redacted() -> None:
    from octop.infra.task_board.acceptance import redact

    cleaned = redact(
        '{"api_key":"private-key","password": "private-password", "secret":"private-secret"} Bearer private-bearer'
    )
    assert "private-" not in cleaned


@pytest.mark.asyncio
async def test_tree_cancel_after_parent_execution_ends(rig: Any) -> None:
    parent = await create(rig)
    child = await create(rig, parent_id=parent)
    await finish(rig, parent)
    await accept(rig, parent)
    waiting = asyncio.Event()

    async def blocked(_: Any) -> str:
        await waiting.wait()
        return "done"

    rig.delivery.deliver = AsyncMock(side_effect=blocked)
    await action(rig, "confirm", child)
    await action(rig, "run", child)
    await asyncio.sleep(0)
    await action(rig, "cancel", parent, cascade=True)
    await rig.service.shutdown()
    assert rig.service.snapshot(rig.uid).tasks[1].runs[-1].state == "interrupted"
