"""Daily report behavior uses separate display and execution histories."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from octop.infra.agents.manager import AgentManager
from octop.infra.cron.delivery import CronDeliveryCommand, CronDeliveryService
from octop.infra.cron.report import ReportOptions, report_session_key
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.devices.service import DeviceService
from octop.infra.execution.service import ExecutionService
from octop.infra.gateway.threads import ThreadRegistry


@pytest.mark.asyncio
@pytest.mark.parametrize("new_conversation", [False, True])
@pytest.mark.parametrize("include_previous", [False, True])
async def test_report_conversation_and_context_are_independent(
    tmp_path: Path, new_conversation: bool, include_previous: bool
) -> None:
    db = SqlitePool(tmp_path / "reports.db")
    run_migrations(db)
    repos = RepoBundle.from_pool(db)
    owner = repos.user_repo.create(username="report-owner", role="user", password_hash="unused")
    repos.agent_repo.create(agent_id="report-agent", user_id=owner, name="Agent")
    key = report_session_key(agent_id="report-agent", user_id=owner, cron_id="daily")
    registry = ThreadRegistry(session_repo=repos.session_repo, thread_repo=repos.thread_repo)
    await registry.get_or_create_by_key(
        session_key=key,
        agent_id="report-agent",
        user_id=owner,
        channel_type="dashboard",
        channel_chat_type="report-daily",
    )
    await registry.get_or_create(
        agent_id="report-agent",
        user_id=owner,
        channel_type="weixin",
        channel_subject_id="original-subject",
        channel_id="original-channel",
    )
    origin_key = ThreadRegistry.make_key(
        agent_id="report-agent", channel_type="weixin", channel_subject_id="original-subject"
    )
    repos.cron_repo.create(
        cron_id="daily",
        agent_id="report-agent",
        user_id=owner,
        trigger="interval:60",
        prompt="Make a report",
        session_key=key,
        task_type="agent",
        kind="daily_report",
        meta={"daily_report": ReportOptions(new_conversation, include_previous, 1).as_dict()},
    )
    devices = DeviceService(repos)
    enrolled = devices.enroll(
        owner_user_id=owner,
        name="Laptop",
        platform="windows",
        capabilities=[],
        permissions=[],
        roots=[],
        trust_mode="owner",
    )
    device_id = enrolled["device"]["device_id"]
    execution = ExecutionService(devices)
    execution.save_selection(
        owner,
        repos.session_repo.get(key).thread_id,
        {"device_id": device_id, "target_kind": "device", "work_mode": "agentic"},
    )
    requests: list[dict[str, Any]] = []
    runner = AgentManager.__new__(AgentManager)
    runner._device_service = devices
    runner.get_config = lambda _agent: {}

    async def stream(_agent: str, request: dict[str, Any]):
        prepared = runner._prepare_stream_request(_agent, request)
        assert prepared["configurable"]["octop_device_target"]["device_id"] == device_id
        requests.append(request)
        repos.thread_repo.append_artifacts(
            request["thread_id"], ["daily.txt"], agent_id="report-agent"
        )
        yield {"type": "token", "content": f"report {len(requests)}"}

    async def locked(_agent: str, _key: str, operation: Any) -> None:
        await operation()

    async def append(_thread: str, messages: list[Any]) -> list[Any]:
        return messages

    harness = MagicMock()
    harness.aappend_messages = append
    harness.graph = None
    harness.aget_history = AsyncMock(return_value=[])
    agents = MagicMock()
    agents._device_service = devices
    agents.get_agent.return_value = harness
    agents.get_row.return_value = None
    agents.default_mcp_servers.return_value = []
    agents.device_mcp_pack_for_turn.return_value = ([], [])
    agents.merge_turn_mcp_servers.return_value = []
    agents.stream = stream
    agents.delete_thread_checkpoint = AsyncMock(return_value=True)
    gateway = MagicMock()
    gateway.thread_registry = registry
    gateway.run_in_session = locked
    gateway.require_session.side_effect = lambda _agent, session_key: repos.session_repo.get(
        session_key
    )
    gateway.observe_dashboard_resume = AsyncMock()
    gateway.push_session_text = AsyncMock()
    gateway.notify_dashboard_push = AsyncMock()
    service = CronDeliveryService(gateway=gateway, agent_manager=agents, repos=repos)
    options = ReportOptions(new_conversation, include_previous, 1)
    command = CronDeliveryCommand(
        cron_id="daily",
        cron_name="Daily report",
        agent_id="report-agent",
        user_id=owner,
        session_key=key,
        prompt="Make a report",
        fresh_thread=new_conversation,
        task_type="agent",
        model=None,
        mcp_servers=(),
        report=options,
        report_origin_session=origin_key,
    )
    await service.deliver(command)
    first_thread = repos.session_repo.get(key).thread_id
    await service.deliver(command)
    second_thread = repos.session_repo.get(key).thread_id

    assert (first_thread != second_thread) is new_conversation
    assert requests[0]["thread_id"] != first_thread
    assert requests[1]["thread_id"] != second_thread
    assert requests[0]["thread_id"] != requests[1]["thread_id"]
    assert execution.selection(owner, requests[0]["thread_id"])["device_id"] == device_id
    assert execution.selection(owner, requests[1]["thread_id"])["device_id"] == device_id
    assert execution.selection(owner, second_thread)["device_id"] == device_id
    assert repos.thread_repo.get(second_thread).artifacts[0].path == "daily.txt"
    prior = [m.content for m in requests[1]["messages"] if isinstance(m, AIMessage)]
    assert prior == (["report 1"] if include_previous else [])
    assert repos.cron_report_repo.recent(
        owner=owner, agent="report-agent", cron="daily", limit=2
    ) == ["report 1", "report 2"]
    assert all(
        row.channel_type != "cron_internal"
        for row in repos.thread_repo.list_by_agent_user(agent_id="report-agent", user_id=owner)
    )
    assert len(repos.thread_repo.list_by_session(session_key=key)) == (2 if new_conversation else 1)
    assert agents.delete_thread_checkpoint.await_count == 2
    pushed = gateway.push_session_text.await_args_list
    assert [call.args[0].channel_type for call in pushed] == [
        "dashboard",
        "weixin",
        "dashboard",
        "weixin",
    ]

    async def failed_stream(_agent: str, _request: dict[str, Any]):
        yield {"type": "hitl_required"}

    agents.stream = failed_stream
    with pytest.raises(RuntimeError, match="interaction"):
        await service.deliver(command)
    assert repos.cron_report_repo.recent(
        owner=owner, agent="report-agent", cron="daily", limit=2
    ) == ["report 1", "report 2"]
    db.close()


@pytest.mark.asyncio
async def test_report_lock_serializes_runs_independently_of_conversation_rotation() -> None:
    service = CronDeliveryService(gateway=MagicMock(), agent_manager=MagicMock(), repos=MagicMock())
    service.cleanup_report_executions = AsyncMock()
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def run(command):
        calls.append(command)
        started.set()
        await release.wait()
        return "report"

    service._deliver = run
    command = CronDeliveryCommand(
        cron_id="daily",
        cron_name="Daily",
        agent_id="a",
        user_id=1,
        session_key="rotating",
        prompt="Report",
        fresh_thread=True,
        task_type="agent",
        model=None,
        mcp_servers=(),
        report=ReportOptions(new_conversation=True),
    )
    first = asyncio.create_task(service.deliver(command))
    await started.wait()
    second = asyncio.create_task(service.deliver(command))
    await asyncio.sleep(0.02)
    assert len(calls) == 1
    release.set()
    assert await asyncio.gather(first, second) == ["report", "report"]


def test_only_completed_reports_are_available_to_their_owner_and_task(tmp_path: Path) -> None:
    db = SqlitePool(tmp_path / "scope.db")
    run_migrations(db)
    repos = RepoBundle.from_pool(db)
    owner = repos.user_repo.create(username="owner", role="user", password_hash="unused")
    other = repos.user_repo.create(username="other", role="user", password_hash="unused")
    repos.agent_repo.create(agent_id="agent", user_id=owner, name="Agent")
    for task in ("one", "two"):
        repos.cron_repo.create(
            cron_id=task,
            agent_id="agent",
            user_id=owner,
            trigger="interval:60",
            prompt="Report",
            session_key="session",
            task_type="agent",
        )
    for attempt, task, status in (
        ("first", "one", "completed"),
        ("second", "one", "failed"),
        ("third", "one", "completed"),
        ("other-task", "two", "completed"),
    ):
        repos.cron_attempt_repo.create(attempt, owner, "agent", task, None, "manual")
        repos.cron_report_repo.save(
            attempt=attempt, owner=owner, agent="agent", cron=task, thread="thread", output=attempt
        )
        repos.cron_attempt_repo.update(owner, attempt, status)
    assert repos.cron_report_repo.recent(owner=owner, agent="agent", cron="one", limit=5) == [
        "first",
        "third",
    ]
    assert repos.cron_report_repo.recent(owner=owner, agent="agent", cron="one", limit=1) == [
        "third"
    ]
    assert repos.cron_report_repo.recent(owner=other, agent="agent", cron="one", limit=5) == []
    db.close()


@pytest.mark.asyncio
async def test_failed_checkpoint_cleanup_is_retried_with_transcript_preserved(
    tmp_path: Path,
) -> None:
    db = SqlitePool(tmp_path / "cleanup.db")
    run_migrations(db)
    repos = RepoBundle.from_pool(db)
    owner = repos.user_repo.create(username="owner", role="user", password_hash="x")
    repos.agent_repo.create(agent_id="agent", user_id=owner, name="Agent")
    repos.thread_repo.insert(
        thread_id="internal",
        agent_id="agent",
        user_id=owner,
        channel_type="cron_internal",
        session_key="key",
    )
    repos.cron_attempt_repo.create("attempt", owner, "agent", "deleted-task", None, "timer")
    repos.cron_attempt_repo.update(owner, "attempt", "running")
    repos.cron_attempt_repo.bind_report_execution(owner, "attempt", "internal")
    repos.cron_attempt_repo.update(owner, "attempt", "failed")
    harness = MagicMock()
    harness.graph = None
    harness.aget_history = AsyncMock(return_value=[AIMessage(content="diagnostic", id="message")])
    manager = MagicMock()
    manager.get_agent.return_value = harness
    manager.delete_thread_checkpoint = AsyncMock(side_effect=[RuntimeError("busy"), True])
    service = CronDeliveryService(gateway=MagicMock(), agent_manager=manager, repos=repos)
    await service.recover_report_executions()
    assert repos.cron_attempt_repo.report_cleanup_scopes()
    await service.recover_report_executions()
    assert repos.cron_attempt_repo.report_cleanup_scopes() == []
    rows, _more = repos.thread_message_repo.page("internal", limit=10)
    assert len(rows) == 1 and "diagnostic" in rows[0].message_json
    db.close()
