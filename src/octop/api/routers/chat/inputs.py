"""Authenticated durable queue and active-run input controls."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from octop.api.common.agent import assert_agent_access
from octop.api.deps import current_user, get_server
from octop.api.routers.chat.models import (
    ChatInputReceiptBody,
    ChatInputsBody,
    QueuedInputBody,
    SteerInputBody,
)
from octop.api.routers.chat.turn import (
    build_dashboard_inbound,
    prepare_dashboard_turn,
    turn_has_content,
)

router = APIRouter()


@router.get(
    "/agents/{agent_id}/threads/{thread_id}/inputs",
    summary="Inspect durable queued messages and active run controls",
    response_model=ChatInputsBody,
)
async def list_inputs(
    agent_id: str,
    thread_id: str,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    assert_agent_access(server, agent_id, user)
    return server.app_runtime.gateway.inputs.list(int(user.id), agent_id, thread_id)


@router.post(
    "/agents/{agent_id}/threads/{thread_id}/inputs",
    summary="Persist a message for FIFO execution after the active turn",
    response_model=ChatInputReceiptBody,
)
async def queue_input(
    agent_id: str,
    thread_id: str,
    body: QueuedInputBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    assert_agent_access(server, agent_id, user)
    service = server.app_runtime.gateway.inputs
    service.assert_scope(int(user.id), agent_id, thread_id)
    turn = body.turn.to_turn_body()
    if turn.thread_id != thread_id or not turn_has_content(turn):
        raise HTTPException(422, "queued turn must contain content and target this thread")
    encoded = json.dumps(
        {"turn": body.turn.model_dump(mode="json"), "snapshot": body.snapshot}, sort_keys=True
    )
    if len(encoded.encode()) > 2 * 1024 * 1024:
        raise HTTPException(413, "queued input metadata exceeds supported size")
    request_key = hashlib.sha256(encoded.encode()).hexdigest()
    try:
        old = service.existing_queue(
            int(user.id), agent_id, thread_id, body.command_id, request_key
        )
        if old is not None:
            return old
        prepared = await prepare_dashboard_turn(
            server, agent_id=agent_id, user=user, turn=turn, persist_selection=False
        )
        inbound = build_dashboard_inbound(
            agent_id=agent_id,
            user_id=int(user.id),
            prepared=prepared,
            turn=turn,
            ws_connection_id=f"queue:{body.command_id}",
            user_is_admin=bool(getattr(user, "is_admin", False)),
        )
        return service.enqueue(
            int(user.id),
            agent_id,
            thread_id,
            body.command_id,
            body.snapshot,
            inbound,
            request_key=request_key,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.delete(
    "/agents/{agent_id}/threads/{thread_id}/inputs/{command_id}",
    summary="Withdraw a message that has not been dispatched",
    response_model=ChatInputReceiptBody,
)
async def withdraw_input(
    agent_id: str,
    thread_id: str,
    command_id: str,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    assert_agent_access(server, agent_id, user)
    try:
        return server.app_runtime.gateway.inputs.withdraw(
            int(user.id), agent_id, thread_id, command_id
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post(
    "/agents/{agent_id}/threads/{thread_id}/inputs/steer",
    summary="Insert plain text into the identified active run at a safe point",
    response_model=ChatInputReceiptBody,
)
async def steer_input(
    agent_id: str,
    thread_id: str,
    body: SteerInputBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    assert_agent_access(server, agent_id, user)
    if body.thread_id != thread_id:
        raise HTTPException(422, "steering thread does not match the URL")
    try:
        return server.app_runtime.gateway.inputs.steer(
            int(user.id), agent_id, thread_id, body.command_id, body.run_id, body.text
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
