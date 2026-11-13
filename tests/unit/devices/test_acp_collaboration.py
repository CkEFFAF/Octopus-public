"""Only real ACP session and event data become independent collaboration history."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import ToolMessage, messages_from_dict
from octop_harness.acp.models import ACPConfig, ACPRunnerConfig

from octop.api.routers.chat.serialize import _serialize_history_message
from octop.infra.conversations.acp_transcript import ACPTranscript
from octop.infra.conversations.collaboration import thread_metadata
from octop.infra.devices.acp_bridge import (
    RequestACPService,
    bind_remote_acp_service,
    build_request_acp_tool,
)
from octop.infra.history.service import HistoryArchive
from octop.infra.history.store import HistoryStore
from tests.unit.conversations.test_agent_collaboration import collaboration as collaboration_rig

collaboration = collaboration_rig


class FakeACP:
    def __init__(self):
        self.config = ACPConfig(
            runners={
                "codex": ACPRunnerConfig(
                    enabled=True, command="fake", env={"PRIVATE_TOKEN": "private-runner-value"}
                )
            }
        )
        self.device_id = "authorized-device"
        self.session = None
        self.state = "completed"
        self.counter = 0
        self.paused = asyncio.Event()

    def _binding(self):
        return "/approved", "linux", 1

    async def get_session(self, *_):
        return self.session

    async def run_turn(self, **kwargs):
        if self.state == "handshake_failed":
            raise ValueError("no handshake")
        if self.session is None or kwargs.get("restart"):
            self.counter += 1
            self.session = SimpleNamespace(acp_session_id=f"actual-session-{self.counter}")
        await kwargs["on_message"](
            {"type": "text", "text": "Actual ACP response private-runner-value"}, True
        )
        if self.state == "cancel":
            self.paused.set()
            await asyncio.Event().wait()
        if self.state == "failed":
            raise ValueError("private-runner-value must not appear in error")
        return {
            "status": self.state,
            "event": {"type": "text", "text": "Actual ACP response"},
            "suspended_permission": SimpleNamespace(
                summary="Write file", options=[{"optionId": "allow_once", "name": "Allow once"}]
            ),
        }

    async def resume_permission(self, **kwargs):
        self.state = "completed"
        await kwargs["on_message"]({"type": "text", "text": "Actual resumed response"}, True)
        return {"status": "completed"}

    async def close_all_sessions(self):
        self.session = None


@pytest.fixture
async def acp_rig(collaboration, tmp_path, monkeypatch):
    c = collaboration
    parent = await c.registry.get_or_create(
        agent_id="expert",
        user_id=c.owner,
        channel_type="dashboard",
        channel_subject_id=str(c.owner),
    )
    store = HistoryStore(tmp_path / "history.db", identity="acp-test")
    archive = HistoryArchive(
        store, c.repos.thread_message_repo, c.repos.trajectory_event_repo, enabled=True
    )
    notify = AsyncMock()
    recorder = ACPTranscript(c.repos, archive, notify)
    fake = FakeACP()
    service = RequestACPService(
        config=fake.config,
        devices=SimpleNamespace(),
        owner=c.owner,
        agent_id="expert",
        transcript=recorder,
    )
    monkeypatch.setattr(service, "_selected", lambda *_: fake)
    yield SimpleNamespace(
        c=c, parent=parent, archive=archive, fake=fake, service=service, notify=notify
    )
    store.close()


async def run(rig, **overrides):
    return await rig.service.run_turn(
        thread_id=rig.parent,
        runner="codex",
        cwd="/approved",
        prompt_blocks=[{"type": "text", "text": "Real expert prompt"}],
        on_message=AsyncMock(),
        **overrides,
    )


async def history(rig, thread):
    async def legacy(_):
        return []

    return [
        _serialize_history_message(msg)
        for msg in messages_from_dict(await rig.archive.all_messages(thread, legacy))
    ]


async def test_real_acp_session_is_separate_linked_and_readable_after_restart(acp_rig):
    rig = acp_rig
    first = await run(rig)
    tid = first["collaboration_thread_id"]
    assert tid != rig.parent
    second = await run(rig)
    assert second["collaboration_thread_id"] == tid
    row = rig.c.repos.thread_repo.get(tid)
    metadata = thread_metadata(rig.c.repos, [row])[tid]
    assert metadata["category"] == "agent_collaboration"
    assert metadata["collaboration_source"] == {
        "kind": "acp",
        "parent_thread_id": rig.parent,
        "runner_name": "codex",
        "acp_session_id": "actual-session-1",
        "device_id": "authorized-device",
    }
    assert (
        rig.c.registry.get_bound_thread_id(
            rig.c.registry.dashboard_key(agent_id="expert", user_id=rig.c.owner)
        )
        == rig.parent
    )
    messages = await history(rig, tid)
    assert len(messages) == 4
    assert messages[0]["sender"] == {"kind": "expert", "id": "expert", "name": "Research expert"}
    assert messages[1]["sender"] == {"kind": "acp", "id": "codex", "name": "codex"}
    assert "Actual ACP response" in str(messages)
    assert "private-runner-value" not in str(messages) + str(metadata)
    assert "PRIVATE_TOKEN" not in str(metadata)
    assert (await run(rig, restart=True))["collaboration_thread_id"] != tid


async def test_permission_and_actual_resume_keep_original_session(acp_rig):
    rig = acp_rig
    rig.fake.state = "permission_required"
    result = await run(rig)
    tid = result["collaboration_thread_id"]
    messages = await history(rig, tid)
    assert messages[-1]["status"] == "permission_required"
    assert "allow_once" in str(messages[-1])
    resumed = await rig.service.resume_permission(
        acp_session_id="actual-session-1", option_id="allow_once", on_message=AsyncMock()
    )
    assert resumed["collaboration_thread_id"] == tid
    assert "Actual resumed response" in str(await history(rig, tid))


@pytest.mark.parametrize("state", ["failed", "cancel"])
async def test_error_and_cancellation_are_recorded_without_secret_or_success(acp_rig, state):
    rig = acp_rig
    rig.fake.state = state
    task = asyncio.create_task(run(rig))
    if state == "cancel":
        await asyncio.wait_for(rig.fake.paused.wait(), 5)
        task.cancel()
    with pytest.raises(asyncio.CancelledError if state == "cancel" else ValueError):
        await task
    tid = rig.service.collaboration_threads[(rig.parent, "codex")]
    messages = await history(rig, tid)
    assert messages[-1]["status"] == ("cancelled" if state == "cancel" else "error")
    assert "private-runner-value" not in str(messages)


async def test_failed_handshake_is_a_failed_attempt_without_fabricated_session(acp_rig):
    rig = acp_rig
    rig.fake.state = "handshake_failed"
    with pytest.raises(ValueError):
        await run(rig)
    tid = rig.service.collaboration_threads[(rig.parent, "codex")]
    row = rig.c.repos.thread_repo.get(tid)
    source = thread_metadata(rig.c.repos, [row])[tid]["collaboration_source"]
    assert source["kind"] == "acp_attempt" and source["acp_session_id"] == ""
    assert (await history(rig, tid))[-1]["status"] == "error"


async def test_parent_tool_result_has_real_child_link_in_artifact(acp_rig, monkeypatch, tmp_path):
    rig = acp_rig
    config = {"configurable": {"thread_id": rig.parent, "user": rig.c.owner}}
    monkeypatch.setattr("octop.infra.devices.acp_bridge.get_config", lambda: config)
    monkeypatch.setattr("octop_harness.builtin.tools.acp_runner.get_config", lambda: config)
    bind_remote_acp_service("collaboration-test", rig.service)
    tool = build_request_acp_tool("collaboration-test", rig.fake.config, tmp_path)
    result = await tool.ainvoke(
        {
            "type": "tool_call",
            "id": "parent-call",
            "name": "acp_runner",
            "args": {"action": "start", "runner": "codex", "message": "Actual prompt"},
        }
    )
    assert isinstance(result, ToolMessage)
    assert (
        result.artifact["collaboration_thread_id"]
        == rig.service.collaboration_threads[(rig.parent, "codex")]
    )
    assert result.artifact["parent_thread_id"] == rig.parent
    assert "Actual ACP response" in result.content
    assert "private-runner-value" not in result.content
    serialized = _serialize_history_message(result)
    assert serialized["content"][0]["artifact"] == result.artifact


async def test_device_rejection_before_handshake_has_attempt_link(acp_rig, monkeypatch, tmp_path):
    rig = acp_rig
    from octop.infra.errors import ErrorCode, OctopError

    config = {"configurable": {"thread_id": rig.parent, "user": rig.c.owner}}
    monkeypatch.setattr("octop.infra.devices.acp_bridge.get_config", lambda: config)

    def rejected(*_):
        raise OctopError.localized(ErrorCode.FORBIDDEN)

    monkeypatch.setattr(rig.service, "_selected", rejected)
    bind_remote_acp_service("rejected-acp-test", rig.service)
    tool = build_request_acp_tool("rejected-acp-test", rig.fake.config, tmp_path)
    result = await tool.ainvoke(
        {
            "type": "tool_call",
            "id": "denied",
            "name": "acp_runner",
            "args": {"action": "start", "runner": "codex", "message": "Denied actual attempt"},
        }
    )
    tid = result.artifact["collaboration_thread_id"]
    assert rig.fake.session is None
    row = rig.c.repos.thread_repo.get(tid)
    assert thread_metadata(rig.c.repos, [row])[tid]["collaboration_source"]["kind"] == "acp_attempt"
    assert (await history(rig, tid))[-1]["status"] == "error"


async def test_legacy_archive_setting_keeps_transcript_and_sender_readable(acp_rig):
    rig = acp_rig
    rig.service.transcript = ACPTranscript(rig.c.repos, None)
    tid = (await run(rig))["collaboration_thread_id"]
    rows, _ = rig.c.repos.thread_message_repo.page(tid, limit=10, offset=0)
    import json

    messages = [
        _serialize_history_message(msg)
        for msg in messages_from_dict([json.loads(row.message_json) for row in rows])
    ]
    assert messages[0]["sender"]["kind"] == "expert"
    assert messages[1]["sender"]["kind"] == "acp"


async def test_running_transcript_does_not_publish_an_empty_unrenderable_message(acp_rig):
    rig = acp_rig
    record = await rig.service.transcript.begin(
        owner=rig.c.owner,
        agent_id="expert",
        parent=rig.parent,
        runner="codex",
        acp_session_id="live-session",
        device_id=None,
        prompt="Real pending prompt",
        private_values=[],
    )
    messages = await history(rig, record["thread_id"])
    assert len(messages) == 1 and messages[0]["sender"]["kind"] == "expert"
    await rig.service.transcript.finish(record, "Actual reply", "completed")


async def test_external_work_input_preserves_sender_without_finishing_active_archive_turn(acp_rig):
    rig = acp_rig
    from langchain_core.messages import HumanMessage, message_to_dict

    from octop.infra.conversations.collaboration import SENDER_KEY

    turn = rig.archive.begin("expert", rig.parent)
    sender = {"kind": "machine", "id": "credential", "name": "Codex"}
    wire = message_to_dict(
        HumanMessage(
            content="Supplement", id="stable-command", additional_kwargs={SENDER_KEY: sender}
        )
    )
    for _ in range(2):
        assert rig.archive.append_external_message("expert", rig.parent, "stable-command", wire)
    assert rig.archive.store.turn(rig.parent)["status"] == "active"
    messages = await history(rig, rig.parent)
    assert len(messages) == 1 and messages[0]["sender"] == sender
    rig.archive.finish(turn["id"], "completed")


@pytest.mark.parametrize("detail", ["source.py", "x" * 128000], ids=["short", "bounded"])
@pytest.mark.parametrize("final_callback", [False, True])
async def test_tool_callback_does_not_drop_the_final_result_answer(
    acp_rig, monkeypatch, detail, final_callback
):
    rig = acp_rig

    async def actual_lifecycle(**kwargs):
        rig.fake.session = SimpleNamespace(acp_session_id="tool-session")
        await kwargs["on_message"]({"type": "tool_start", "kind": "read", "detail": detail}, True)
        final = {"type": "text", "text": "FINAL ANSWER MUST SURVIVE"}
        if final_callback:
            await kwargs["on_message"](final, True)
        return {"status": "completed", "event": final}

    monkeypatch.setattr(rig.fake, "run_turn", actual_lifecycle)
    tid = (await run(rig))["collaboration_thread_id"]
    messages = await history(rig, tid)
    text = str(messages[-1]["content"])
    assert "[tool_call] read" in text
    assert "FINAL ANSWER MUST SURVIVE" in text


async def test_identical_final_text_callback_is_saved_once(acp_rig, monkeypatch):
    rig = acp_rig

    async def actual_lifecycle(**kwargs):
        rig.fake.session = SimpleNamespace(acp_session_id="text-session")
        final = {"type": "text", "text": "ONE FINAL ANSWER"}
        await kwargs["on_message"](final, True)
        return {"status": "completed", "event": final}

    monkeypatch.setattr(rig.fake, "run_turn", actual_lifecycle)
    tid = (await run(rig))["collaboration_thread_id"]
    assert str((await history(rig, tid))[-1]["content"]).count("ONE FINAL ANSWER") == 1


async def test_permission_lookup_tolerates_session_map_changes_during_await():
    service = RequestACPService(
        config=ACPConfig(), devices=SimpleNamespace(), owner=1, agent_id="expert"
    )
    started, release = asyncio.Event(), asyncio.Event()

    async def blocked_lookup(*_):
        started.set()
        await release.wait()
        return SimpleNamespace(acp_session_id="other-session")

    unmatched = SimpleNamespace(get_session=blocked_lookup)
    matching = SimpleNamespace(
        get_session=AsyncMock(return_value=SimpleNamespace(acp_session_id="wanted")),
        resume_permission=AsyncMock(return_value={"status": "completed"}),
    )
    service._session_targets = {("first", "codex"): unmatched, ("second", "codex"): matching}
    task = asyncio.create_task(
        service.resume_permission(
            acp_session_id="wanted", option_id="allow_once", on_message=AsyncMock()
        )
    )
    await asyncio.wait_for(started.wait(), 5)
    service._session_targets.pop(("first", "codex"))
    service._session_targets[("third", "codex")] = unmatched
    service._session_targets[("fourth", "codex")] = unmatched
    release.set()
    assert await task == {"status": "completed"}
    matching.resume_permission.assert_awaited_once()


async def test_device_enabled_runner_records_failed_attempt_when_hub_template_is_disabled(
    acp_rig, monkeypatch, tmp_path
):
    rig = acp_rig
    rig.service.config = ACPConfig(
        runners={"codex": ACPRunnerConfig(enabled=False, command="hub-template")}
    )
    rig.fake.state = "handshake_failed"
    config = {"configurable": {"thread_id": rig.parent, "user": rig.c.owner}}
    monkeypatch.setattr("octop.infra.devices.acp_bridge.get_config", lambda: config)
    monkeypatch.setattr("octop_harness.builtin.tools.acp_runner.get_config", lambda: config)
    bind_remote_acp_service("device-runner-failure", rig.service)
    tool = build_request_acp_tool("device-runner-failure", rig.service.config, tmp_path)
    result = await tool.ainvoke(
        {
            "type": "tool_call",
            "id": "device-call",
            "name": "acp_runner",
            "args": {"action": "start", "runner": "codex", "message": "Device invocation"},
        }
    )
    tid = result.artifact["collaboration_thread_id"]
    assert rig.fake.session is None
    assert result.artifact["parent_thread_id"] == rig.parent
    row = rig.c.repos.thread_repo.get(tid)
    metadata = thread_metadata(rig.c.repos, [row])[tid]
    assert metadata["actor"] == {"kind": "expert", "id": "expert", "name": "Research expert"}
    assert metadata["collaboration_source"] == {
        "kind": "acp_attempt",
        "parent_thread_id": rig.parent,
        "runner_name": "codex",
        "acp_session_id": "",
        "device_id": "authorized-device",
    }
    assert (await history(rig, tid))[-1]["status"] == "error"
