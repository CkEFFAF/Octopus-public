"""Unconfirmed dispatches are recovered read-only, never replayed."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from acp import RequestError

from octop.infra.acp_remote.agent import RemoteAcpAgent
from octop.infra.acp_remote.cloud import CloudClient
from octop.infra.acp_remote.sessions import SessionStore


def adapter(tmp_path):
    cloud = MagicMock(spec=CloudClient)
    cloud.server = "https://cloud.example"
    cloud.identity = AsyncMock(return_value={"credential_id": "key"})
    cloud.create_thread = AsyncMock(return_value={"thread_id": "root"})
    cloud.history = AsyncMock(return_value={"messages": []})
    cloud.detail = AsyncMock(
        return_value={"task_id": "task", "status": "completed", "reported_outcome": "完成"}
    )
    cloud.create_work_item = AsyncMock(return_value={"task_id": "task"})
    cloud.lookup_command = AsyncMock(return_value={"task_id": "task"})
    cloud.input_receipt = AsyncMock(return_value={"task_id": "task"})
    store = SessionStore(tmp_path / "mapping.sqlite3")
    agent = RemoteAcpAgent(
        cloud=cloud,
        expert_id="expert",
        credential_id="key",
        store=store,
        poll_interval=0.001,
        poll_timeout=None,
    )
    return agent, cloud, store


@pytest.mark.asyncio
async def test_lost_create_response_recovers_without_repeating_post(tmp_path):
    agent, cloud, store = adapter(tmp_path)
    session = await agent.new_session(cwd=str(tmp_path))
    cloud.create_work_item.side_effect = httpx.ReadError("response lost")
    with pytest.raises(RequestError):
        await agent.prompt(session.session_id, [{"type": "text", "text": "执行"}])
    pending = store.get(session.session_id)["pending"]
    assert pending["command_id"] == cloud.create_work_item.call_args.kwargs["command_id"]
    # New adapter and a new cache connection simulate a process restart.
    agent = RemoteAcpAgent(
        cloud=cloud, expert_id="expert", credential_id="key", store=SessionStore(store.path)
    )
    result = await agent.prompt(session.session_id, [{"type": "text", "text": "执行"}])
    assert result.stop_reason == "end_turn"
    assert cloud.create_work_item.await_count == 1
    cloud.lookup_command.assert_awaited_once_with(pending["command_id"])


@pytest.mark.asyncio
async def test_unknown_retains_pending_and_never_starts_another_task(tmp_path):
    agent, cloud, store = adapter(tmp_path)
    session = await agent.new_session(cwd=str(tmp_path))
    cloud.detail.return_value = {"task_id": "task", "status": "unknown"}
    for _ in range(2):
        with pytest.raises(RequestError):
            await agent.prompt(session.session_id, [{"type": "text", "text": "执行"}])
    assert store.get(session.session_id)["pending"]
    assert cloud.create_work_item.await_count == 1
    with pytest.raises(RequestError):
        await agent.prompt(session.session_id, [{"type": "text", "text": "另一个任务"}])
    assert cloud.create_work_item.await_count == 1


@pytest.mark.asyncio
async def test_lost_input_response_uses_input_receipt(tmp_path):
    agent, cloud, store = adapter(tmp_path)
    session = await agent.new_session(cwd=str(tmp_path))
    row = store.get(session.session_id)
    row.update(
        remote_task_id="task",
        pending={"kind": "input", "command_id": "input-command", "text": "补充"},
    )
    store.put(session.session_id, row)
    await agent.prompt(session.session_id, [{"type": "text", "text": "补充"}])
    cloud.input_receipt.assert_awaited_once_with("task", "input-command")
    cloud.lookup_command.assert_not_called()
    cloud.add_input.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_is_reported_only_after_server_confirmation(tmp_path):
    agent, cloud, store = adapter(tmp_path)
    row = {"remote_task_id": "task", "pending": {"text": "执行"}, "history": []}
    cloud.detail.side_effect = [
        {"task_id": "task", "status": "running"},
        {"task_id": "task", "status": "cancelled"},
    ]
    cancelled = asyncio.Event()
    cancelled.set()
    response = await agent._poll("session", row, cancelled)
    assert response.stop_reason == "cancelled"
    assert cloud.detail.await_count == 2
    cloud.cancel.assert_awaited_once()


def test_independent_process_stores_do_not_lose_other_sessions(tmp_path):
    first = SessionStore(tmp_path / "mapping.sqlite3")
    second = SessionStore(first.path)
    first.put("one", {"history": ["a"]})
    second.put("two", {"history": ["b"]})
    assert first.get("two") == {"history": ["b"]}
    assert second.get("one") == {"history": ["a"]}


@pytest.mark.parametrize(
    "url", ["http://cloud.example", "https://u:p@cloud.example", "https://cloud.example/?token=x"]
)
def test_credentials_cannot_be_sent_over_insecure_or_ambiguous_endpoints(url):
    with pytest.raises(ValueError):
        CloudClient(url, "unused")
