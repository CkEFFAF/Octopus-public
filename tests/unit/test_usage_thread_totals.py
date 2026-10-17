"""tests/unit/test_usage_thread_totals.py"""

from __future__ import annotations

import json
from pathlib import Path

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.agents import AgentRepo
from octop.infra.db.repos.usage import UsageRepo
from octop.infra.db.repos.users import UserRepo
from octop.infra.db.services import RepoBundle


def test_thread_totals_aggregate(tmp_path: Path):
    db = SqlitePool(tmp_path / "u.db")
    run_migrations(db)
    uid = UserRepo(db).create(username="u", password_hash="h", role="user")
    AgentRepo(db).create(agent_id="a1", user_id=uid, name="a")
    repo = UsageRepo(db)
    repo.record(
        agent_id="a1",
        user_id=uid,
        thread_id="thr_1",
        input_tokens=10,
        uncached_input_tokens=4,
        cache_read_tokens=6,
        output_tokens=5,
        model="m",
    )
    repo.record(
        agent_id="a1",
        user_id=uid,
        thread_id="thr_1",
        input_tokens=3,
        output_tokens=2,
        model="m",
    )
    totals = repo.thread_totals(agent_id="a1", thread_id="thr_1")
    assert totals["input_tokens"] == 13
    assert totals["uncached_input_tokens"] == 7
    assert totals["cache_read_tokens"] == 6
    assert totals["output_tokens"] == 7
    assert totals["total_tokens"] == 20
    assert totals["model_calls"] == 2
    assert totals["turns"] == 2


def test_context_fallback_uses_last_call_not_billing_sum(tmp_path):
    db = SqlitePool(tmp_path / "window.db")
    run_migrations(db)
    repos = RepoBundle.from_pool(db)
    owner = repos.user_repo.create(username="owner", password_hash="x", role="admin")
    repos.agent_repo.create(agent_id="gpu", user_id=owner, name="GPU")
    repos.thread_repo.insert(
        thread_id="t", agent_id="gpu", user_id=owner, channel_type="dashboard", session_key="s"
    )
    repo = UsageRepo(db)
    repo.record(
        agent_id="gpu",
        user_id=owner,
        thread_id="t",
        input_tokens=4_364_569,
        output_tokens=100,
        model_calls=51,
    )
    assert repo.last_thread_input_tokens(agent_id="gpu", thread_id="t") == 0
    with db.connect() as c:
        c.execute(
            "INSERT INTO thread_messages(thread_id,seq,role,message_json,created_at) VALUES(?,?,?,?,?)",
            ("t", 1, "ai", json.dumps({"data": {"usage_metadata": {"input_tokens": 418_748}}}), 1),
        )
        c.commit()
    assert repo.last_thread_input_tokens(agent_id="gpu", thread_id="t") == 418_748
    assert repo.last_thread_input_tokens(agent_id="foreign", thread_id="t") == 0
    db.close()


def test_migration_repair_preserves_fully_cached_input(tmp_path: Path) -> None:
    db = SqlitePool(tmp_path / "cached.db")
    run_migrations(db)
    uid = UserRepo(db).create(username="u", password_hash="h", role="user")
    AgentRepo(db).create(agent_id="a1", user_id=uid, name="a")
    repo = UsageRepo(db)
    repo.record(
        agent_id="a1",
        user_id=uid,
        thread_id="thr_1",
        input_tokens=10,
        uncached_input_tokens=0,
        cache_read_tokens=10,
        output_tokens=1,
    )

    run_migrations(db)

    totals = repo.thread_totals(agent_id="a1", thread_id="thr_1")
    assert totals["uncached_input_tokens"] == 0
    assert totals["cache_read_tokens"] == 10
