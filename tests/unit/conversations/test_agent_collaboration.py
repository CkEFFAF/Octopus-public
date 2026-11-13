"""Authenticated participants survive task dispatch, revocation and history reads."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import HumanMessage, messages_from_dict
from pydantic import ValidationError

from octop.api.routers.chat.models import ChatTurnBody
from octop.api.routers.chat.serialize import _serialize_history_message
from octop.api.routers.chat.turn import (
    PreparedDashboardTurn,
    build_dashboard_inbound,
    content_parts_from_dashboard_turn,
)
from octop.infra.auth.agent_access_keys import AgentAccessKeyService
from octop.infra.conversations.collaboration import (
    SENDER_KEY,
    live_sender,
    machine_actor,
    thread_metadata,
)
from octop.infra.conversations.heat import ThreadHeatService
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.work_items.models import WorkItemCreate, WorkItemInputCreate
from octop.infra.work_items.service import WorkItemsService


@pytest.fixture
def collaboration(tmp_path):
    pool = SqlitePool(tmp_path / "collaboration.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="owner", role="admin", password_hash="x")
    repos.agent_repo.create(agent_id="expert", user_id=owner, name="Research expert")
    keys = AgentAccessKeyService(repos)
    key = keys.create(
        owner,
        name="Codex",
        days=1,
        scopes=["tasks.create", "tasks.read", "tasks.input"],
        expert_ids=["expert"],
    )
    principal = keys.authenticate(key["secret"], "127.0.0.1")
    registry = ThreadRegistry(session_repo=repos.session_repo, thread_repo=repos.thread_repo)
    yield SimpleNamespace(
        repos=repos, owner=owner, keys=keys, key=key, principal=principal, registry=registry
    )
    pool.close()


async def test_machine_category_and_actor_survive_revocation_and_filter_before_limit(collaboration):
    c = collaboration
    human = await c.registry.get_or_create(
        agent_id="expert",
        user_id=c.owner,
        channel_type="dashboard",
        channel_subject_id=str(c.owner),
    )
    c.repos.thread_repo.set_pinned(human, True)
    remote = await c.keys.create_session(c.principal, "expert", c.registry)
    tid = remote["thread_id"]
    assert (
        c.registry.get_bound_thread_id(c.registry.dashboard_key(agent_id="expert", user_id=c.owner))
        == human
    )
    rows = ThreadHeatService(c.repos).list(c.owner, "expert", 1, category="agent_collaboration")
    assert [row.thread_id for row, _ in rows] == [tid]
    actor = {"kind": "machine", "id": c.principal.credential_id, "name": "Codex"}
    assert thread_metadata(c.repos, [rows[0][0]])[tid]["actor"] == actor
    c.keys.revoke(c.owner, c.principal.credential_id)
    assert thread_metadata(c.repos, [rows[0][0]])[tid]["actor"] == actor
    assert (
        ThreadHeatService(c.repos).list(c.owner, "expert", 1, category="user")[0][0].thread_id
        == human
    )


async def test_work_item_initial_and_each_input_have_their_actual_actor(collaboration, monkeypatch):
    c = collaboration
    origin = await c.keys.create_session(c.principal, "expert", c.registry)
    gateway = SimpleNamespace(
        thread_registry=c.registry,
        emit_thread_changed=AsyncMock(),
        observe_dashboard_resume=AsyncMock(),
        emit_task_changed=AsyncMock(),
    )
    captured = []

    async def deliver(command):
        captured.append(command)
        return "Actual worker reply"

    harness = SimpleNamespace(aappend_messages=AsyncMock())
    service = WorkItemsService(
        repos=c.repos,
        gateway=gateway,
        registry=SimpleNamespace(get_agent=lambda _: harness),
        delivery=SimpleNamespace(deliver=deliver),
    )
    monkeypatch.setattr(service, "_schedule_dispatch", lambda *_: None)
    body = WorkItemCreate(
        command_id="create",
        agent_id="expert",
        origin_thread_id=origin["thread_id"],
        title="Work",
        instructions="Plan",
    )
    created = await service.create(c.owner, body, credential_id=c.principal.credential_id)
    await service._dispatch(c.owner, created["task_id"])
    actor = machine_actor(c.repos, c.owner, c.principal.credential_id)
    assert captured[0].sender == actor
    row = c.repos.work_item_repo.get(c.owner, created["task_id"])
    worker = c.repos.thread_repo.get(row["worker_thread_id"])
    assert thread_metadata(c.repos, [worker])[worker.thread_id]["actor"] == actor
    c.repos.work_item_repo.update(c.owner, created["task_id"], status="running")
    await service.add_input(
        c.owner,
        created["task_id"],
        WorkItemInputCreate(command_id="machine-input", text="Follow up"),
        credential_id=c.principal.credential_id,
    )
    machine_message = harness.aappend_messages.await_args.args[1][0]
    assert machine_message.additional_kwargs[SENDER_KEY] == actor
    assert gateway.observe_dashboard_resume.await_args.args[3]["sender"] == actor
    await service.add_input(
        c.owner,
        created["task_id"],
        WorkItemInputCreate(command_id="human-input", text="Owner reply"),
    )
    human_message = harness.aappend_messages.await_args.args[1][0]
    assert SENDER_KEY not in human_message.additional_kwargs
    assert "sender" not in gateway.observe_dashboard_resume.await_args.args[3]
    c.keys.revoke(c.owner, c.principal.credential_id)
    assert service._creation_sender(row) == actor


def test_client_sender_fields_cannot_create_authenticated_identity():
    fake = {"kind": "machine", "id": "guessed", "name": "Codex"}
    with pytest.raises(ValidationError):
        WorkItemInputCreate(command_id="forged", text="hello", sender=fake)
    with pytest.raises(ValidationError):
        WorkItemCreate(
            command_id="forged",
            agent_id="expert",
            origin_thread_id="human",
            title="hello",
            sender=fake,
        )
    turn = ChatTurnBody(
        messages=[
            {
                "role": "user",
                "content": "Actual text",
                "sender": fake,
                "additional_kwargs": {"sender": fake, SENDER_KEY: fake},
            }
        ]
    )
    prepared = PreparedDashboardTurn(
        thread_id="human",
        session_key="human",
        mcp_servers=[],
        skills=None,
        model_ref=None,
        inbound_content=content_parts_from_dashboard_turn(turn),
        composer_context=None,
        inbound_attachments=[],
    )
    inbound = build_dashboard_inbound(
        agent_id="expert", user_id=1, prepared=prepared, turn=turn, ws_connection_id="test"
    )
    assert inbound.text == "Actual text"
    assert "sender" not in inbound.metadata and SENDER_KEY not in inbound.metadata


def test_history_and_live_sender_only_use_server_stamped_message_kwargs():
    actor = {"kind": "machine", "id": "issued-key", "name": "Codex"}
    message = HumanMessage(content="Hello", additional_kwargs={SENDER_KEY: actor})
    wire = json.loads(json.dumps({"type": "human", "data": message.model_dump()}))
    restored = messages_from_dict([wire])[0]
    assert _serialize_history_message(restored)["sender"] == actor
    assert "sender" not in _serialize_history_message(HumanMessage(content="Human reply"))
    assert (
        live_sender({"type": "user", "additional_kwargs": {SENDER_KEY: actor}})["sender"] == actor
    )
    assert "sender" not in live_sender({"type": "user", "additional_kwargs": {"sender": actor}})
