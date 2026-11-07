"""One request validates media before durable admission and recovers lost acknowledgements."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import HumanMessage
from octop_gateway.models import ChannelSubject, FileContent, InboundMessage
from tests.unit.gateway.test_chat_input_queue import setup_queue as queue_fixture

from octop.api.routers.chat.inputs import queue_input
from octop.api.routers.chat.models import QueuedInputBody
from octop.infra.errors import ErrorCode, OctopError

setup_queue = queue_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["accepted", "inactive"])
async def test_media_is_validated_once_and_receipt_retry_never_resubmits(
    setup_queue, monkeypatch, outcome
):
    queue, _, owner, *_ = setup_queue
    inbound = InboundMessage(
        channel_id="dashboard",
        channel_type="dashboard",
        channel_subject=ChannelSubject(subject_id=str(owner)),
        content=[
            FileContent(filename="补充.txt", local_path="inbound/qa.txt", mime_type="text/plain")
        ],
        metadata={
            "octop_inbound_attachments": [
                {
                    "filename": "补充.txt",
                    "workspace_path": "inbound/qa.txt",
                    "kind": "file",
                    "resource_id": "res_qa",
                    "version": "a" * 64,
                }
            ]
        },
    )
    human = HumanMessage(
        content="verified resource",
        additional_kwargs={
            "octop_inbound_attachments": inbound.metadata["octop_inbound_attachments"]
        },
    )
    queue.gateway.processor.prepare_steering_message = AsyncMock(return_value=human)
    queue.gateway.emit_thread_changed = AsyncMock()
    queue.agents.steer_stream.return_value = {"status": outcome, "phase": "tool_running"}
    monkeypatch.setattr("octop.api.routers.chat.inputs.assert_agent_access", lambda *args: None)
    monkeypatch.setattr(
        "octop.api.routers.chat.inputs.prepare_dashboard_turn", AsyncMock(return_value=object())
    )
    monkeypatch.setattr(
        "octop.api.routers.chat.inputs.build_dashboard_inbound", lambda **kwargs: inbound
    )
    server = SimpleNamespace(
        app_runtime=SimpleNamespace(
            gateway=SimpleNamespace(
                inputs=queue, emit_thread_changed=queue.gateway.emit_thread_changed
            )
        )
    )
    body = QueuedInputBody(
        command_id="media",
        run_id="run",
        turn={
            "type": "user_turn",
            "thread_id": "thread",
            "messages": [{"role": "user", "content": "file"}],
        },
        snapshot={"attachments": [{"filename": "client snapshot"}]},
    )
    first = await queue_input(
        "agent", "thread", body, user=SimpleNamespace(id=owner), server=server
    )
    second = await queue_input(
        "agent", "thread", body, user=SimpleNamespace(id=owner), server=server
    )
    assert first["event_id"] == second["event_id"]
    assert first["status"] == ("accepted" if outcome == "accepted" else "queued")
    queue.gateway.processor.prepare_steering_message.assert_awaited_once()
    assert queue.agents.steer_stream.call_count == 1


@pytest.mark.asyncio
async def test_rejected_media_cannot_leave_a_dispatchable_input(setup_queue, monkeypatch):
    queue, _, owner, *_ = setup_queue
    inbound = InboundMessage(
        channel_id="dashboard",
        channel_type="dashboard",
        content=[FileContent(filename="missing.txt", local_path="inbound/missing.txt")],
        metadata={"octop_inbound_attachments": [{"kind": "file"}]},
    )
    queue.gateway.processor.prepare_steering_message = AsyncMock(
        side_effect=OctopError(ErrorCode.FORBIDDEN, "resource unavailable")
    )
    monkeypatch.setattr("octop.api.routers.chat.inputs.assert_agent_access", lambda *args: None)
    monkeypatch.setattr(
        "octop.api.routers.chat.inputs.prepare_dashboard_turn", AsyncMock(return_value=object())
    )
    monkeypatch.setattr(
        "octop.api.routers.chat.inputs.build_dashboard_inbound", lambda **kwargs: inbound
    )
    server = SimpleNamespace(app_runtime=SimpleNamespace(gateway=SimpleNamespace(inputs=queue)))
    body = QueuedInputBody(
        command_id="denied",
        run_id="run",
        turn={
            "type": "user_turn",
            "thread_id": "thread",
            "messages": [{"role": "user", "content": "file"}],
        },
        snapshot={},
    )
    with pytest.raises(OctopError):
        await queue_input("agent", "thread", body, user=SimpleNamespace(id=owner), server=server)
    assert queue.list(owner, "agent", "thread")["inputs"] == []
    queue.agents.steer_stream.assert_not_called()
