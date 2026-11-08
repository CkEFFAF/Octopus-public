import json
import time
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage, message_to_dict

from octop.infra.conversations.activity import record_user_request
from octop.infra.conversations.heat import ThreadHeatService, overview_due
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.history.store import HistoryStore


@pytest.fixture
def activity(tmp_path: Path):
    pool = SqlitePool(tmp_path / "activity.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="owner", password_hash="test", role="admin")
    other = repos.user_repo.create(username="other", password_hash="test", role="user")
    repos.agent_repo.create(agent_id="expert", user_id=owner, name="Expert")
    repos.agent_repo.create(agent_id="other", user_id=other, name="Other")
    for thread, agent, user in [
        ("old", "expert", owner),
        ("recent", "expert", owner),
        ("pin", "expert", owner),
        ("foreign", "other", other),
    ]:
        repos.thread_repo.insert(
            thread_id=thread,
            agent_id=agent,
            user_id=user,
            channel_type="dashboard",
            session_key=thread,
            last_active=1,
        )
    yield repos, owner, other
    pool.close()


def test_activity_deduplicates_inputs_and_excludes_foreign_threads(activity):
    repos, owner, other = activity
    request = {"messages": [HumanMessage(content="private sentinel", id="message-1")]}
    record_user_request(repos, owner, "expert", "old", request)
    record_user_request(repos, owner, "expert", "old", request)
    assert not repos.thread_activity_repo.record(other, "expert", "old", "forged")
    signals = repos.thread_activity_repo.signals(owner, "expert", time.time())
    assert signals["old"]["interactions_24h"] == 1
    with repos.db.connect() as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(thread_user_activity)").fetchall()
        }
        assert not {"content", "text", "message_json", "payload_json"} & columns
        assert (
            conn.execute("SELECT source_id FROM thread_user_activity").fetchone()[0]
            == "human:message-1"
        )


def test_heat_ranks_before_pagination_and_keeps_pins_first(activity):
    repos, owner, _ = activity
    repos.thread_repo.set_pinned("pin", True)
    repos.thread_repo.touch_last_active("recent")
    repos.work_item_repo.insert(
        {
            "task_id": "work",
            "owner_user_id": owner,
            "agent_id": "expert",
            "command_id": "work-create",
            "origin_thread_id": "old",
            "title": "Background work",
            "instructions": "task",
            "status": "running",
        }
    )
    ranked = ThreadHeatService(repos).list(owner, "expert", 2)
    assert [row.thread_id for row, _ in ranked] == ["pin", "old"]
    assert ranked[1][1]["level"] == "running"
    assert ranked[1][1]["background_count"] == 1
    assert ThreadHeatService(repos).list(owner, "other") == []


def test_quiet_policy_uses_real_idle_time_and_defers_live_answers():
    now = 2_000_000_000.0
    due, reason = overview_due(
        now=now, generated_at=0, last_user_at=now - 30, score=10, active=False, samples=[]
    )
    assert due == now + 270 and reason == "recent_conversation"
    due, reason = overview_due(
        now=now, generated_at=now - 120, last_user_at=now - 3600, score=80, active=False, samples=[]
    )
    assert due == now + 1680 and reason == "heat_interval"
    due, reason = overview_due(
        now=now, generated_at=0, last_user_at=0, score=0, active=True, samples=[]
    )
    assert due >= now + 120 and reason == "answer_running"


def test_quiet_policy_learns_hours_only_with_sufficient_samples():
    now = 2_000_000_000.0
    samples = [now - day * 86400 + second for day in range(1, 5) for second in range(10)]
    due, reason = overview_due(
        now=now,
        generated_at=now - 3600,
        last_user_at=now - 600,
        score=0,
        active=False,
        samples=samples,
    )
    assert now < due <= now + 6 * 3600 and reason == "quiet_window"
    assert overview_due(
        now=now,
        generated_at=now - 3600,
        last_user_at=now - 600,
        score=0,
        active=False,
        samples=samples[:10],
    ) == (now, "idle")


def test_archive_seed_reads_metadata_and_shares_canonical_message_ids(
    tmp_path: Path, activity, monkeypatch
):
    repos, owner, _ = activity
    store = HistoryStore(tmp_path / "history.db", identity="activity-test")
    now = time.time()
    with store.db.connect() as conn:
        conn.execute(
            "INSERT INTO segments(thread_id,agent_id,format,legacy_start,trajectory_start) VALUES ('old','expert','v2',0,0)"
        )
        segment = conn.execute("SELECT id FROM segments").fetchone()[0]
        conn.execute(
            "INSERT INTO turns(id,segment_id,status,started_at) VALUES ('turn',?,'done',?)",
            (segment, now),
        )
        store.put_document(
            conn,
            doc_id="message:turn:0",
            thread_id="old",
            turn_id="turn",
            kind="message",
            seq=1,
            value=message_to_dict(
                HumanMessage(
                    id="canonical",
                    content="secret body",
                    additional_kwargs={"checkpoint_ts": now * 1000},
                )
            ),
        )
        for seq, message in enumerate(
            [
                HumanMessage(id="cron:delivery:human", content="scheduled"),
                HumanMessage(
                    id="synthetic",
                    content="summary",
                    additional_kwargs={"lc_source": "summarization"},
                ),
            ],
            start=2,
        ):
            store.put_document(
                conn,
                doc_id=f"message:turn:{seq}",
                thread_id="old",
                turn_id="turn",
                kind="message",
                seq=seq,
                value=message_to_dict(message),
            )
    monkeypatch.setattr(
        store, "_decode", lambda *args: pytest.fail("activity must not resolve private bodies")
    )
    samples = store.user_activity_samples(now - 86400)
    assert samples == [{"thread_id": "old", "source_id": "human:canonical", "occurred_at": now}]
    repos.thread_activity_repo.seed_archive(samples)
    assert not repos.thread_activity_repo.record(owner, "expert", "old", "human:canonical")
    store.db.close()


def test_legacy_seed_excludes_cron_and_synthetic_humans(activity):
    repos, owner, _ = activity
    now = time.time()
    messages = [
        HumanMessage(id="real", content="user"),
        HumanMessage(id="cron:daily:human", content="scheduled"),
        HumanMessage(
            id="summary", content="summary", additional_kwargs={"lc_source": "summarization"}
        ),
        HumanMessage(id="skill", content="skill", additional_kwargs={"lc_source": "pinned_skill"}),
    ]
    with repos.db.connect() as conn:
        for seq, message in enumerate(messages, start=1):
            conn.execute(
                "INSERT INTO thread_messages(thread_id,seq,message_id,role,message_json,created_at) VALUES (?,?,?,?,?,?)",
                ("old", seq, message.id, "human", json.dumps(message_to_dict(message)), now),
            )
    repos.thread_activity_repo.seed_legacy(now - 86400)
    assert repos.thread_activity_repo.signals(owner, "expert", now)["old"]["interactions_24h"] == 1


def test_deferral_preserves_prior_provider_failures(activity):
    repos, owner, _ = activity
    repo = repos.conversation_metadata_repo
    job = repo.enqueue(owner, "expert", "old", "auto", {}, "auto:old")
    with repos.db.connect() as conn:
        conn.execute(
            "UPDATE thread_metadata_jobs SET status='retry',attempts=2,not_before=0 WHERE job_id=?",
            (job["job_id"],),
        )
    claimed = repo.claim()
    assert claimed["attempts"] == 3
    assert repo.defer_auto(claimed, time.time() + 300, "recent_conversation")
    deferred = repo.job(owner, "old", job["job_id"])
    assert deferred["attempts"] == 2 and deferred["status"] == "queued"
    assert not repo.defer_auto(claimed, time.time() + 600, "quiet_window")


def test_unavailable_job_observation_does_not_make_a_session_running(activity):
    repos, owner, _ = activity
    repos.run_event_repo.save(
        event_id="job",
        owner=owner,
        agent_id="expert",
        thread_id="old",
        run_id="run",
        context_id=None,
        kind="job",
        status="running",
        payload={"observation": {"status": "unavailable"}},
    )
    values = repos.thread_activity_repo.signals(owner, "expert", time.time())
    assert values.get("old", {}).get("background_count", 0) == 0
