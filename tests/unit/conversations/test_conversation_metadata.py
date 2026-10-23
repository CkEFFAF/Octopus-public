from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from octop.infra.conversations.models import (
    BriefPatch,
    GeneratedTitle,
    HistoryBatchRequest,
    MetadataSettings,
)
from octop.infra.conversations.service import ConversationService
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.thread_messages import ThreadMessageInput
from octop.infra.db.services import RepoBundle
from octop.infra.errors import OctopError


@pytest.fixture
def environment(tmp_path: Path) -> tuple[ConversationService, RepoBundle]:
    pool = SqlitePool(tmp_path / "conversation.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="alice", password_hash="h", role="user")
    repos.user_repo.create(username="bob", password_hash="h", role="user")
    repos.agent_repo.create(agent_id="agent", user_id=owner, name="Agent")
    repos.thread_repo.insert(
        thread_id="thread",
        agent_id="agent",
        user_id=owner,
        channel_type="dashboard",
        session_key="session",
    )
    repos.settings_repo.set_active_model(owner, "provider", "model")
    store = SimpleNamespace(
        is_model_ref_usable=lambda ref: ref == "provider/model", build_harness_configs=lambda: []
    )
    manager = SimpleNamespace(
        _repos=repos,
        providers_for_user=lambda uid: (
            store if uid == 1 else SimpleNamespace(is_model_ref_usable=lambda ref: False)
        ),
        steering_status=lambda agent, thread: None,
    )
    return ConversationService(manager, "Asia/Shanghai"), repos


def append(
    repos: RepoBundle,
    text: str,
    *,
    identity: str = "message",
    role: str = "human",
    stamp: int | None = None,
) -> None:
    repos.thread_message_repo.append_if_ready(
        "thread",
        [
            ThreadMessageInput(
                message_id=identity,
                role=role,
                message_json=json.dumps({"type": role, "data": {"content": text}}),
                created_at=stamp or int(time.time()),
            )
        ],
    )


def claim(
    service: ConversationService, repos: RepoBundle, kind: str = "brief", command: str = "test"
) -> dict[str, Any]:
    service.request(1, "agent", "thread", kind, command)
    value = repos.conversation_metadata_repo.claim()
    assert value is not None
    return value


def fake_output(purpose: str, payload: dict[str, Any]) -> dict[str, Any]:
    if purpose == "thread_title":
        return {"title": "会话信息整理"}
    messages = payload.get("messages") or payload.get("original_sources") or []
    refs = (
        [messages[0]["ref"]]
        if messages
        else [{"kind": "event", "id": payload["events"][0]["ref"]["id"]}]
    )
    return {
        "one_liner": "整理会话信息",
        "objective": "让会话内容与进度易于理解",
        "next_actions": [{"text": "补充验收证据", "source_refs": refs}],
        "events": [{"kind": "request", "text": "提出会话整理需求", "source_refs": refs}],
    }


def test_batch_failures_survive_later_success_with_pagination_and_owner_scope(environment):
    service, repos = environment
    repo = repos.conversation_metadata_repo
    for i in range(24):
        repos.thread_repo.insert(
            thread_id=f"history-{i}",
            agent_id="agent",
            user_id=1,
            channel_type="dashboard",
            session_key=f"history-{i}",
        )
    batch = service.start_history_batch(1, HistoryBatchRequest(command_id="recovery"))
    with repos.db.transaction() as conn:
        conn.execute(
            "UPDATE thread_metadata_jobs SET status='failed',error_code='METADATA_INVALID_OUTPUT',updated_at=100 WHERE owner_user_id=1"
        )
    later = repo.enqueue(1, "agent", "thread", "brief", {}, "later-success")
    with repos.db.transaction() as conn:
        conn.execute(
            "UPDATE thread_metadata_jobs SET status='ready',updated_at=200 WHERE job_id=?",
            (later["job_id"],),
        )
    restored = service.history_batch(1)
    assert restored.failed == 25 and restored.recovered == 1
    # Historical totals remain immutable; latest failure selection excludes recovery.
    current = repo.organization_page(1, age="all", status="failed", agent=None, offset=0, limit=100)
    assert current["total"] == 24
    pages = [
        repo.organization_page(
            1, age="all", status="failed", agent=None, offset=offset, limit=20, batch=batch.batch_id
        )
        for offset in (0, 20)
    ]
    assert [len(p["items"]) for p in pages] == [20, 5]
    assert all(p["total"] == 25 for p in pages)
    row = next(r for p in pages for r in p["items"] if r["thread_id"] == "thread")
    assert row["status"] == "failed" and row["latest_status"] == "ready"
    assert row["last_attempt_at"] == 100 and row["last_success_at"] == 200
    assert row["error_code"] == "METADATA_INVALID_OUTPUT"
    assert (
        repo.organization_page(
            2, age="all", status="all", agent=None, offset=0, limit=100, batch=batch.batch_id
        )["total"]
        == 0
    )
    assert (
        repo.organization_page(
            1, age="all", status="all", agent=None, offset=0, limit=100, batch="missing"
        )["total"]
        == 0
    )
    # A new failure makes the conversation unresolved again.
    retry = repo.enqueue(1, "agent", "thread", "brief", {}, "new-failure")
    with repos.db.transaction() as conn:
        conn.execute(
            "UPDATE thread_metadata_jobs SET status='failed',updated_at=300 WHERE job_id=?",
            (retry["job_id"],),
        )
    assert service.history_batch(1).recovered == 0


def test_organization_age_buckets_failures_and_atomic_selection(environment, monkeypatch):
    service, repos = environment
    now = 2_000_000_000.0
    monkeypatch.setattr("octop.infra.db.repos.organization_history.time.time", lambda: now)
    for name, age in (("recent", 0.5), ("one", 1), ("three", 3), ("five", 5), ("seven", 7)):
        repos.thread_repo.insert(
            thread_id=name, agent_id="agent", user_id=1, channel_type="dashboard", session_key=name
        )
        with repos.db.transaction() as conn:
            conn.execute(
                "UPDATE thread_metadata SET generated_at=? WHERE thread_id=?",
                (now - age * 86400, name),
            )
    repo = repos.conversation_metadata_repo
    for age, expected in (
        ("never", "thread"),
        ("d1", "recent"),
        ("d3", "one"),
        ("d5", "three"),
        ("d7", "five"),
        ("older", "seven"),
    ):
        page = repo.organization_page(1, age=age, status="all", agent=None, offset=0, limit=20)
        assert [r["thread_id"] for r in page["items"]] == [expected]
    job = repo.enqueue(1, "agent", "seven", "brief", {}, "failed-attempt")
    with repos.db.transaction() as conn:
        conn.execute(
            "UPDATE thread_metadata_jobs SET status='failed',error_code='METADATA_INVALID_OUTPUT',updated_at=? WHERE job_id=?",
            (now, job["job_id"]),
        )
    page = repo.organization_page(1, age="older", status="failed", agent=None, offset=0, limit=20)
    assert page["total"] == 1
    assert page["items"][0]["last_success_at"] == now - 7 * 86400
    assert page["items"][0]["last_attempt_at"] == now
    batch = service.start_history_batch(
        1, HistoryBatchRequest(command_id="old-failed", age_filter="older", status_filter="failed")
    )
    assert batch.total == 1 and batch.started_at == now and batch.finished_at == 0
    with repos.db.connect() as conn:
        rows = conn.execute(
            "SELECT thread_id FROM thread_metadata_jobs WHERE dedup_key LIKE 'batch:%'"
        ).fetchall()
    assert [r["thread_id"] for r in rows] == ["seven"]
    assert (
        repo.organization_page(2, age="all", status="all", agent=None, offset=0, limit=20)["total"]
        == 0
    )


def test_organization_lists_all_failed_conversations_with_success_time_preserved(environment):
    _, repos = environment
    repo = repos.conversation_metadata_repo
    for index in range(25):
        thread = f"failed-{index:02d}"
        repos.thread_repo.insert(
            thread_id=thread,
            agent_id="agent",
            user_id=1,
            channel_type="dashboard",
            session_key=thread,
        )
        repos.thread_repo.update_title(thread, f"Experiment {index}")
        job = repo.enqueue(1, "agent", thread, "brief", {}, thread)
        with repos.db.transaction() as conn:
            conn.execute(
                "UPDATE thread_metadata_jobs SET status='failed',error_code='METADATA_INVALID_OUTPUT',result_json=? WHERE job_id=?",
                (
                    json.dumps(
                        {"diagnostic": {"issues": [{"path": "one_liner", "type": "missing"}]}}
                    ),
                    job["job_id"],
                ),
            )
    first = repo.organization_page(1, age="never", status="failed", agent=None, offset=0, limit=20)
    second = repo.organization_page(
        1, age="never", status="failed", agent=None, offset=20, limit=20
    )
    assert first["total"] == second["total"] == 25
    assert len(first["items"]) == 20 and len(second["items"]) == 5
    assert len({r["thread_id"] for r in first["items"] + second["items"]}) == 25
    assert all(
        r["title"].startswith("Experiment") and r["last_success_at"] == 0 for r in first["items"]
    )
    assert first["items"][0]["diagnostic"]["issues"][0]["path"] == "one_liner"


@pytest.mark.asyncio
async def test_real_wire_messages_generate_title_and_attributed_brief(environment, monkeypatch):
    service, repos = environment
    append(repos, "请为长会话建立清晰的标题和进度概括。")
    calls = []

    async def generate(manager, job, model, payload, schema, purpose):
        calls.append((job["owner_user_id"], model, purpose))
        return json.dumps(fake_output(purpose, payload), ensure_ascii=False)

    monkeypatch.setattr("octop.infra.conversations.service.generate_json", generate)
    await service.process(claim(service, repos))
    brief = service.brief(1, "agent", "thread")
    assert brief.title == "会话信息整理"
    assert brief.title_source == "automatic"
    assert brief.overview["objective"] == "让会话内容与进度易于理解"
    assert brief.provenance["coverage"]["message_seq"] == 1
    assert brief.provenance["freshness"] == "current"
    assert all(owner == 1 and model == "provider/model" for owner, model, _ in calls)
    source = service.source(1, "agent", "thread", "message", "1")
    assert source.text == "请为长会话建立清晰的标题和进度概括。"
    assert service.events(1, "agent", "thread", "today").events
    preview = repos.conversation_metadata_repo.list_briefs(1, "agent", ["thread"])["thread"]
    assert preview["recent_events"] == ["提出会话整理需求"]
    assert "stage" in preview
    assert preview["next_action"] == "补充验收证据"
    assert preview["current_progress"] == ""
    assert preview["blocker"] == ""


@pytest.mark.asyncio
async def test_model_blocker_suggestion_does_not_override_work_state(environment, monkeypatch):
    service, repos = environment
    append(repos, "测试尚未进行，继续推进工作。")

    async def generate(manager, job, model, payload, schema, purpose):
        output = fake_output(purpose, payload)
        if purpose == "thread_brief":
            output["blockers"] = [
                {"text": "尚未验证", "source_refs": [{"kind": "message", "id": "1"}]}
            ]
        return json.dumps(output, ensure_ascii=False)

    monkeypatch.setattr("octop.infra.conversations.service.generate_json", generate)
    await service.process(claim(service, repos))
    brief = service.brief(1, "agent", "thread")
    assert brief.progress["blockers"]
    assert brief.progress["work_state"] == "in_progress"
    assert (
        repos.conversation_metadata_repo.list_briefs(1, "agent", ["thread"])["thread"]["work_state"]
        == "in_progress"
    )
    changed = service.patch(
        1, "agent", "thread", BriefPatch(expected_revision=brief.revision, work_state="blocked")
    )
    assert changed.progress["work_state"] == "blocked"


@pytest.mark.asyncio
async def test_manual_title_wins_while_model_is_running(environment, monkeypatch):
    service, repos = environment
    append(repos, "整理会话")

    async def generate(manager, job, model, payload, schema, purpose):
        if purpose == "thread_title":
            repos.thread_repo.update_title("thread", "我手动选择的标题")
        return json.dumps(fake_output(purpose, payload), ensure_ascii=False)

    monkeypatch.setattr("octop.infra.conversations.service.generate_json", generate)
    await service.process(claim(service, repos))
    assert repos.thread_repo.get("thread").title == "我手动选择的标题"
    assert repos.thread_repo.get("thread").title_source == "user"


@pytest.mark.asyncio
async def test_new_source_rejects_late_brief_then_resumes(environment, monkeypatch):
    service, repos = environment
    append(repos, "整理会话")
    changed = False

    async def generate(manager, job, model, payload, schema, purpose):
        nonlocal changed
        if purpose == "thread_brief" and not changed:
            append(repos, "新增约束：不要覆盖人工说明", identity="new")
            changed = True
        return json.dumps(fake_output(purpose, payload), ensure_ascii=False)

    monkeypatch.setattr("octop.infra.conversations.service.generate_json", generate)
    job = claim(service, repos)
    await service.process(job)
    assert service.brief(1, "agent", "thread").provenance["freshness"] == "unavailable"
    assert repos.conversation_metadata_repo.job(1, "thread", job["job_id"])["status"] == "queued"


def test_configuration_cas_owner_scope_and_manual_corrections(environment):
    service, repos = environment
    assert repos.conversation_metadata_repo.save_settings(
        1, 0, MetadataSettings(title_enabled=False).model_dump()
    )
    assert not repos.conversation_metadata_repo.save_settings(1, 0, MetadataSettings().model_dump())
    assert service.config(1).title_enabled is False
    assert service.config(2).title_enabled is True
    with pytest.raises(OctopError):
        service.brief(2, "agent", "thread")
    updated = service.patch(
        1, "agent", "thread", BriefPatch(expected_revision=0, objective="人工目标", note="保留说明")
    )
    assert updated.overview["objective"] == "人工目标"
    with pytest.raises(OctopError):
        service.patch(1, "agent", "thread", BriefPatch(expected_revision=0, objective="旧编辑"))


def test_leases_do_not_run_two_jobs_for_same_owner_and_recover(environment):
    service, repos = environment
    first = claim(service, repos)
    service.request(1, "agent", "thread", "title", "second")
    assert repos.conversation_metadata_repo.claim() is None
    with repos.db.transaction() as conn:
        conn.execute(
            "UPDATE thread_metadata_jobs SET lease_until=0 WHERE job_id=?", (first["job_id"],)
        )
    recovered = repos.conversation_metadata_repo.claim()
    assert recovered is not None
    assert not repos.conversation_metadata_repo.finish(first, "ready")


def test_job_late_receipt_changes_source_without_chat_and_does_not_complete_goal(environment):
    service, repos = environment
    append(repos, "后台任务")
    before = repos.conversation_metadata_repo.get("thread")["source_revision"]
    repos.run_event_repo.save(
        event_id="job:1",
        owner=1,
        agent_id="agent",
        thread_id="thread",
        run_id="run",
        context_id=None,
        kind="job",
        status="running",
        payload={"job_id": "job1"},
    )
    assert service.brief(1, "agent", "thread").progress["execution_state"] == "running"
    repos.run_event_repo.save(
        event_id="job:1",
        owner=1,
        agent_id="agent",
        thread_id="thread",
        run_id="run",
        context_id=None,
        kind="job",
        status="completed",
        payload={"job_id": "job1", "receipt": {"returncode": 0}},
    )
    after = repos.conversation_metadata_repo.get("thread")["source_revision"]
    assert after > before
    assert service.brief(1, "agent", "thread").progress["work_state"] != "completed"
    assert len(service.events(1, "agent", "thread", "today").events) == 2


def test_period_and_empty_digest_never_call_model(environment):
    service, repos = environment
    start, end = service.window("range:2026-10-20:2026-10-20")
    assert end - start == 86400
    result = service.digest_request(1, "agent", "thread", "range:2026-10-20:2026-10-20")
    assert result.summary == ""
    assert repos.conversation_metadata_repo.claim() is None


def test_verification_requires_successful_same_run_receipts_and_never_accepts_goal(environment):
    service, repos = environment

    def save(identity, kind, status, payload, run="run"):
        repos.run_event_repo.save(
            event_id=identity,
            owner=1,
            agent_id="agent",
            thread_id="thread",
            run_id=run,
            context_id=None,
            kind=kind,
            status=status,
            payload=payload,
        )

    save("tool:ok", "tool", "completed", {"receipt": {"returncode": 0}})
    save("tool:failed", "tool", "failed", {})
    save("tool:foreign-run", "tool", "completed", {}, run="other")
    save("tool:nonzero", "tool", "completed", {"receipt": {"returncode": 1}})
    for name, ids in (
        ("backed", ["tool:ok"]),
        ("failed", ["tool:failed"]),
        ("missing", []),
        ("foreign", ["tool:foreign-run"]),
        ("nonzero", ["tool:nonzero"]),
    ):
        save(
            f"workflow:{name}",
            "workflow",
            "completed",
            {
                "version": 1,
                "stages": [{"name": "verify", "status": "completed", "evidence_ids": ids}],
            },
        )
    progress = service.brief(1, "agent", "thread").progress
    assert progress["verification_passed"] == 1
    assert progress["verification_reported"] == 5
    assert progress["work_state"] != "completed"
    assert progress["acceptance"] is None
    before = repos.conversation_metadata_repo.get("thread")["source_revision"]
    save(
        "workflow:backed",
        "workflow",
        "completed",
        {
            "version": 2,
            "stages": [{"name": "verify", "status": "completed", "evidence_ids": ["tool:ok"]}],
        },
    )
    assert repos.conversation_metadata_repo.get("thread")["source_revision"] > before


def test_fork_origin_does_not_copy_acceptance_or_allow_foreign_parent(environment):
    service, repos = environment
    service.patch(1, "agent", "thread", BriefPatch(expected_revision=0, work_state="completed"))
    repos.thread_repo.insert(
        thread_id="child",
        agent_id="agent",
        user_id=1,
        channel_type="dashboard",
        session_key="child",
    )
    repo = repos.conversation_metadata_repo
    repo.record_fork(1, "child", "thread")
    brief = service.brief(1, "agent", "child")
    assert brief.progress["acceptance"] is None
    assert brief.progress["execution_state"] == "idle"
    events = service.events(1, "agent", "child", "today").events
    assert len(events) == 1 and events[0].kind == "fork"
    assert events[0].details["source_thread_id"] == "thread"
    repo.record_fork(2, "child", "thread")
    assert len(service.events(1, "agent", "child", "today").events) == 1


@pytest.mark.asyncio
async def test_failure_preserves_existing_and_has_bounded_retries(environment, monkeypatch):
    service, repos = environment
    append(repos, "整理会话")
    repos.thread_repo.set_title_if_null("thread", "原始占位")

    async def timeout(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr("octop.infra.conversations.service.generate_json", timeout)
    job = claim(service, repos)
    for attempt in range(3):
        await service.process(job)
        row = repos.conversation_metadata_repo.job(1, "thread", job["job_id"])
        assert row["status"] == ("retry" if attempt < 2 else "failed")
        if attempt < 2:
            with repos.db.transaction() as conn:
                conn.execute(
                    "UPDATE thread_metadata_jobs SET not_before=0 WHERE job_id=?", (job["job_id"],)
                )
            job = repos.conversation_metadata_repo.claim()
    assert repos.thread_repo.get("thread").title == "原始占位"


@pytest.mark.asyncio
async def test_title_and_brief_failures_are_independent(environment, monkeypatch):
    service, repos = environment
    append(repos, "分别生成标题和概要")

    async def title_fails(manager, job, model, payload, schema, purpose):
        if purpose == "thread_title":
            raise TimeoutError()
        return json.dumps(fake_output(purpose, payload), ensure_ascii=False)

    monkeypatch.setattr("octop.infra.conversations.service.generate_json", title_fails)
    await service.process(claim(service, repos))
    brief = service.brief(1, "agent", "thread")
    assert brief.overview["objective"]
    assert brief.title_source == "fallback"
    listed = repos.conversation_metadata_repo.list_briefs(1, "agent", ["thread"])
    assert listed["thread"]["one_liner"] == brief.overview["one_liner"]


@pytest.mark.asyncio
async def test_valid_title_survives_invalid_brief(environment, monkeypatch):
    service, repos = environment
    append(repos, "生成会话信息")

    async def brief_fails(manager, job, model, payload, schema, purpose):
        if purpose == "thread_brief":
            return "not JSON"
        return json.dumps(fake_output(purpose, payload), ensure_ascii=False)

    monkeypatch.setattr("octop.infra.conversations.service.generate_json", brief_fails)
    await service.process(claim(service, repos))
    assert service.brief(1, "agent", "thread").title == "会话信息整理"


@pytest.mark.asyncio
async def test_archive_outbox_survives_restart_and_resumed_message_edits(
    environment, tmp_path, monkeypatch
):
    from octop.infra.history.service import HistoryArchive
    from octop.infra.history.store import HistoryStore

    service, repos = environment
    path = tmp_path / "history.db"
    archive = HistoryArchive(
        HistoryStore(path, identity="0035"),
        repos.thread_message_repo,
        repos.trajectory_event_repo,
        enabled=True,
    )
    turn = archive.begin("agent", "thread")
    assert turn is not None
    wire = {"type": "human", "data": {"content": "归档中的会话整理需求"}}
    archive.save_messages(turn, [wire])
    archive.finish(turn["id"], "paused")
    archive.store.close()
    archive = HistoryArchive(
        HistoryStore(path, identity="0035"),
        repos.thread_message_repo,
        repos.trajectory_event_repo,
        enabled=True,
    )
    service.manager._native_management_context = {"history_archive": archive}
    calls = []

    async def generate(manager, job, model, payload, schema, purpose):
        calls.append((purpose, payload))
        return json.dumps(fake_output(purpose, payload), ensure_ascii=False)

    monkeypatch.setattr("octop.infra.conversations.service.generate_json", generate)
    await service.tick()
    assert not archive.store.metadata_changes()
    await service.process(claim(service, repos))
    brief = service.brief(1, "agent", "thread")
    assert brief.title_source == "automatic"
    assert brief.provenance["coverage"]["archive_seq"] == 1
    assert brief.provenance["coverage"]["complete"]
    assert "归档中的" in service.source(1, "agent", "thread", "message", "archive:1").text
    original_event = service.events(1, "agent", "thread", "today").events[0].event_id
    repos.conversation_metadata_repo.save_digest(
        "thread", "before-edit", 1, {"digest_id": "before-edit"}
    )
    assert repos.conversation_metadata_repo.digest("before-edit", "thread") is not None
    resumed = archive.begin("agent", "thread", resume=True)
    archive.save_messages(resumed, [{"type": "human", "data": {"content": "修订后的目标"}}])
    archive.finish(resumed["id"], "completed")
    await service.tick()
    meta = repos.conversation_metadata_repo.get("thread")
    assert meta["source_revision"] > brief.provenance["source_revision"]
    assert meta["snapshot"]["coverage"]["archive_seq"] == 0
    assert "brief" not in meta["snapshot"]
    assert repos.conversation_metadata_repo.event("thread", original_event) is None
    assert repos.conversation_metadata_repo.digest("before-edit", "thread") is None
    await service.process(claim(service, repos, command="after-edit"))
    updated_payload = [payload for purpose, payload in calls if purpose == "thread_brief"][-1]
    assert not updated_payload["previous"]
    assert any(
        "修订后的目标" in str(payload) for purpose, payload in calls if purpose == "thread_brief"
    )
    before_revision = repos.conversation_metadata_repo.get("thread")["revision"]

    async def archive_changes_during_call(manager, job, model, payload, schema, purpose):
        if purpose == "thread_brief":
            later = archive.begin("agent", "thread")
            archive.save_messages(
                later, [{"type": "human", "data": {"content": "模型调用期间出现新来源"}}]
            )
            archive.finish(later["id"], "completed")
        return json.dumps(fake_output(purpose, payload), ensure_ascii=False)

    monkeypatch.setattr(
        "octop.infra.conversations.service.generate_json", archive_changes_during_call
    )
    pending = claim(service, repos, command="during-archive-change")
    await service.process(pending)
    assert repos.conversation_metadata_repo.get("thread")["revision"] == before_revision
    assert service.job(1, "agent", "thread", pending["job_id"]).status == "queued"
    assert service.brief(1, "agent", "thread").provenance["freshness"] in {"stale", "updating"}
    archive.store.close()


@pytest.mark.asyncio
async def test_digest_pages_checkpoint_retry_cache_and_preserve_all_refs(environment, monkeypatch):
    from octop.infra.db.repos.conversation_metadata import record_semantic_event

    service, repos = environment
    stamp = time.time() - 100
    with repos.db.transaction() as conn:
        for i in range(25):
            record_semantic_event(
                conn, "thread", f"fixture:{i}", "progress", {"text": f"进度 {i}"}, stamp + i
            )
    request = service.digest_request(1, "agent", "thread", "today")
    calls = []
    fail_second = True

    async def generate(manager, job, model, payload, schema, purpose):
        nonlocal fail_second
        calls.append(payload)
        if payload["previous_summary"] and fail_second:
            fail_second = False
            raise TimeoutError()
        return json.dumps(
            {
                "summary": f"已合并至第 {payload['events'][-1]['data']} 条",
                "event_ids": [r["event_id"] for r in payload["events"]],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("octop.infra.conversations.service.generate_json", generate)
    for _ in range(8):
        with repos.db.transaction() as conn:
            conn.execute(
                "UPDATE thread_metadata_jobs SET not_before=0 WHERE job_id=?", (request.job_id,)
            )
        job = repos.conversation_metadata_repo.claim()
        if job is None:
            break
        # Reconstruct the worker each time; only durable checkpoints survive.
        await ConversationService(service.manager, service.timezone).process(job)
        status = service.job(1, "agent", "thread", request.job_id)
        if status.status == "ready":
            break
    assert status.status == "ready"
    digest = service.digest(1, "agent", "thread", status.result["digest_id"])
    assert len(digest.event_ids) == 25
    assert len(calls) == 5
    assert calls[1] == calls[2]
    assert service.digest_request(1, "agent", "thread", "today").digest_id == digest.digest_id


def test_manual_reopen_clears_prior_acceptance(environment):
    service, _ = environment
    brief = service.patch(
        1, "agent", "thread", BriefPatch(expected_revision=0, work_state="completed")
    )
    assert brief.progress["acceptance"]
    reopened = service.patch(
        1, "agent", "thread", BriefPatch(expected_revision=brief.revision, objective="新的目标")
    )
    assert reopened.objective_version > brief.objective_version
    assert reopened.progress["work_state"] == "in_progress"
    assert reopened.progress["acceptance"] is None


def test_expired_worker_cannot_renew_or_publish_error(environment):
    service, repos = environment
    job = claim(service, repos)
    with repos.db.transaction() as conn:
        conn.execute(
            "UPDATE thread_metadata_jobs SET lease_until=0 WHERE job_id=?", (job["job_id"],)
        )
    assert not repos.conversation_metadata_repo.renew(job)
    assert not repos.conversation_metadata_repo.finish(job, "failed", error="expired")
    assert repos.conversation_metadata_repo.get("thread")["last_error"] == ""


@pytest.mark.asyncio
async def test_agent_read_tools_use_only_injected_current_identity(environment, monkeypatch):
    from octop.infra.conversations.tools import build_conversation_tools

    service, repos = environment
    append(repos, "仅当前会话可读")
    service.manager._config = SimpleNamespace(default_timezone="Asia/Shanghai")
    tools = {tool.name: tool for tool in build_conversation_tools(service.manager, "agent")}
    monkeypatch.setattr("octop.infra.conversations.tools.tool_context", lambda: (1, "thread"))
    source = json.loads(
        await tools["read_conversation_source"].ainvoke({"kind": "message", "id": "1"})
    )
    assert source["text"] == "仅当前会话可读"
    monkeypatch.setattr("octop.infra.conversations.tools.tool_context", lambda: (2, "thread"))
    assert json.loads(await tools["get_conversation_brief"].ainvoke({}))["error"] == "FORBIDDEN"
    overridden = await tools["get_conversation_brief"].ainvoke(
        {"user_id": 1, "thread_id": "thread"}
    )
    assert json.loads(overridden)["error"] == "FORBIDDEN"


def test_server_calendar_day_windows_respect_dst(environment):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    service, _ = environment
    service.timezone = "America/New_York"
    start, end = service.window("range:2026-03-08:2026-03-08")
    assert end - start == 23 * 3600
    start, end = service.window("last_7d")
    local = datetime.fromtimestamp(start, ZoneInfo(service.timezone))
    assert local.hour == local.minute == local.second == 0
    assert local.date() == datetime.now(ZoneInfo(service.timezone)).date() - timedelta(days=6)


@pytest.mark.asyncio
async def test_explicit_digest_retry_recovers_failed_range_without_new_sources(
    environment, monkeypatch
):
    from octop.infra.db.repos.conversation_metadata import record_semantic_event

    service, repos = environment
    with repos.db.transaction() as conn:
        record_semantic_event(
            conn, "thread", "retry-fixture", "progress", {"text": "一条进展"}, time.time() - 10
        )
    request = service.digest_request(1, "agent", "thread", "today")

    async def invalid(*args):
        return "invalid JSON"

    monkeypatch.setattr("octop.infra.conversations.service.generate_json", invalid)
    await service.process(repos.conversation_metadata_repo.claim())
    assert service.job(1, "agent", "thread", request.job_id).status == "failed"
    retry = service.digest_request(1, "agent", "thread", "today")
    assert retry.job_id == request.job_id
    assert retry.status == "queued"
    assert retry.attempts == 0

    async def valid(manager, job, model, payload, schema, purpose):
        return json.dumps(
            {"summary": "进展摘要", "event_ids": [r["event_id"] for r in payload["events"]]}
        )

    monkeypatch.setattr("octop.infra.conversations.service.generate_json", valid)
    await service.process(repos.conversation_metadata_repo.claim())
    assert service.job(1, "agent", "thread", request.job_id).status == "ready"
    assert not service.brief(1, "agent", "thread").provenance["last_error"]


def test_all_history_batch_crosses_fifty_and_preserves_owner_scope_and_idempotency(environment):
    service, repos = environment
    repos.agent_repo.create(agent_id="second", user_id=1, name="Second")
    repos.agent_repo.create(agent_id="shared", user_id=2, name="Shared")
    repos.agent_repo.set_shared("shared", True)
    repos.agent_repo.create(agent_id="private", user_id=2, name="Private")
    for i in range(65):
        repos.thread_repo.insert(
            thread_id=f"old-{i}",
            agent_id="agent" if i < 55 else "second",
            user_id=1,
            channel_type="dashboard",
            session_key=f"old-{i}",
        )
    for thread, agent, owner in [
        ("own-shared", "shared", 1),
        ("other-shared", "shared", 2),
        ("no-access", "private", 1),
    ]:
        repos.thread_repo.insert(
            thread_id=thread,
            agent_id=agent,
            user_id=owner,
            channel_type="dashboard",
            session_key=thread,
        )
    repos.thread_repo.update_title("thread", "人工命名")
    with repos.db.transaction() as conn:
        conn.execute("UPDATE thread_metadata SET auto_enrolled=0")
    service.patch(1, "agent", "thread", BriefPatch(expected_revision=0, objective="人工目标"))
    first = service.start_history_batch(1, HistoryBatchRequest(command_id="all-history"))
    assert first.total == first.queued == 67
    assert (
        service.start_history_batch(1, HistoryBatchRequest(command_id="duplicate-click")) == first
    )
    assert service.start_history_batch(1, HistoryBatchRequest(command_id="all-history")) == first
    assert service.history_batch(2) is None
    assert repos.conversation_metadata_repo.get("thread")["manual"]["objective"] == "人工目标"
    assert repos.thread_repo.get("thread").title == "人工命名"
    assert repos.conversation_metadata_repo.get("own-shared")["auto_enrolled"] == 1
    assert repos.conversation_metadata_repo.get("other-shared")["auto_enrolled"] == 0
    assert repos.conversation_metadata_repo.get("no-access")["auto_enrolled"] == 0
    # Claim/finish uses the existing durable worker; constructing a new service restores progress.
    job = repos.conversation_metadata_repo.claim()
    assert job is not None
    # An automatic job from the manual patch can be first; finish it before claiming the batch.
    while job["request"].get("batch_id") != "all-history":
        repos.conversation_metadata_repo.finish(job, "ready")
        job = repos.conversation_metadata_repo.claim()
        assert job is not None
    assert service.history_batch(1).running == 1
    repos.conversation_metadata_repo.finish(job, "failed", error="METADATA_MODEL_UNAVAILABLE")
    restored = ConversationService(service.manager).history_batch(1)
    assert restored.total == 67 and restored.failed == 1 and restored.queued == 66


def test_history_batch_selection_rejects_foreign_threads_and_unavailable_models(environment):
    service, repos = environment
    with pytest.raises(OctopError):
        service.start_history_batch(
            1, HistoryBatchRequest(command_id="missing-agent", thread_ids=["thread"])
        )
    with pytest.raises(OctopError):
        service.start_history_batch(
            1, HistoryBatchRequest(command_id="foreign", agent_id="agent", thread_ids=["missing"])
        )
    assert service.history_batch(1) is None
    repos.settings_repo.set_active_model(1, "missing", "model")
    with pytest.raises(OctopError):
        service.start_history_batch(1, HistoryBatchRequest(command_id="bad-model"))
    assert service.history_batch(1) is None
    repos.settings_repo.set_active_model(1, "provider", "model")
    value = service.start_history_batch(
        1,
        HistoryBatchRequest(
            command_id="selected", agent_id="agent", thread_ids=["thread", "thread"]
        ),
    )
    assert value.total == 1


@pytest.mark.asyncio
async def test_cancelled_batch_revokes_running_lease_and_preserves_completed(environment):
    service, repos = environment
    batch = service.start_history_batch(1, HistoryBatchRequest(command_id="cancel-test"))
    job = repos.conversation_metadata_repo.claim()
    assert job is not None
    with pytest.raises(OctopError):
        service.cancel_history_batch(2, batch.batch_id)
    result = service.cancel_history_batch(1, batch.batch_id)
    assert result.cancelled == 1 and result.running == result.queued == 0
    assert not repos.conversation_metadata_repo.renew(job)
    assert not repos.conversation_metadata_repo.finish(job, "ready")
    assert service.cancel_history_batch(1, batch.batch_id).cancelled == 1


@pytest.mark.asyncio
async def test_cancel_stops_inflight_request_and_prevents_output(environment):
    service, repos = environment
    job = claim(service, repos)
    started, stopped = asyncio.Event(), asyncio.Event()

    async def model(*args):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    with patch("octop.infra.conversations.service.generate_json", side_effect=model):
        task = asyncio.create_task(
            service._call(
                job, "provider/model", {}, GeneratedTitle.model_json_schema(), "thread_title"
            )
        )
        await started.wait()
        service.cancel_job(1, "agent", "thread", job["job_id"])
        with pytest.raises(ValueError, match="METADATA_LEASE_LOST"):
            await asyncio.wait_for(task, timeout=3)
        assert stopped.is_set()


@pytest.mark.asyncio
async def test_invalid_model_format_retries_once_without_echoing_response(environment):
    service, repos = environment
    job = claim(service, repos)
    model = AsyncMock(
        side_effect=['{"secret-private-field": "private-source"}', '{"title":"Readable topic"}']
    )
    with patch("octop.infra.conversations.service.generate_json", model):
        result = await service._call(
            job,
            "provider/model",
            {"messages": []},
            GeneratedTitle.model_json_schema(),
            "thread_title",
        )
    assert result == {"title": "Readable topic"}
    assert model.await_count == 2
    correction = model.call_args_list[1].args[3]["format_correction"]
    assert "private-source" not in correction and "secret-private-field" not in correction
    assert model.call_args_list[0].args[2] == model.call_args_list[1].args[2]


def test_output_diagnostics_keep_paths_but_strip_values_and_unknown_names():
    from pydantic import ValidationError

    from octop.infra.utils.model_diagnostics import safe_diagnostics

    try:
        GeneratedTitle.model_validate({"title": ["secret-value"], "secret-field": "secret-key"})
    except ValidationError as exc:
        value = safe_diagnostics(exc, code="METADATA_INVALID_OUTPUT", stage="title", job_id="job")
    text = json.dumps(value)
    assert "title" in text and "string_type" in text
    assert "secret-value" not in text and "secret-field" not in text and "secret-key" not in text


def test_json_syntax_diagnostics_include_position_without_response_text():
    from octop.infra.utils.model_diagnostics import safe_diagnostics

    try:
        json.loads('{"private-source": secret-value}')
    except json.JSONDecodeError as exc:
        value = safe_diagnostics(exc, code="METADATA_INVALID_OUTPUT", stage="brief", job_id="job")
        assert value["json_position"] == {
            "line": exc.lineno,
            "column": exc.colno,
            "offset": exc.pos,
        }
    assert value["format_failure"] == "invalid_json"
    assert "private-source" not in json.dumps(value) and "secret-value" not in json.dumps(value)
