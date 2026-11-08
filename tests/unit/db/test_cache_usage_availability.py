from pathlib import Path

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.gateway.process.usage_record import UsageTracker, record_turn_usage


def test_unknown_zero_and_mixed_usage_survive_ledger_round_trip(tmp_path: Path) -> None:
    pool = SqlitePool(tmp_path / "usage.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="owner", password_hash="test", role="admin")
    repos.agent_repo.create(agent_id="expert", user_id=owner, name="Expert")
    tracker = UsageTracker()
    tracker.observe(
        {
            "type": "usage",
            "call_id": "known",
            "usage": {"input_tokens": 100, "output_tokens": 1, "cache_read_tokens": 0},
        }
    )
    assert tracker.usage["cache_metrics_reported"] is True
    record_turn_usage(
        repos.usage_repo, agent_id="expert", user_id=owner, thread_id="known", usage=tracker.usage
    )
    assert repos.usage_repo.summary(user_id=owner, granularity="total")["cache_hit_percent"] == 0
    tracker.observe(
        {
            "type": "usage",
            "call_id": "unknown",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 1,
                "cache_metrics_reported": False,
                "cache_read_tokens": 0,
            },
        }
    )
    assert tracker.usage["cache_metrics_reported"] is False
    record_turn_usage(
        repos.usage_repo, agent_id="expert", user_id=owner, thread_id="mixed", usage=tracker.usage
    )
    assert (
        repos.usage_repo.thread_totals(agent_id="expert", thread_id="mixed")[
            "cache_metrics_reported"
        ]
        is False
    )
    summary = repos.usage_repo.summary(user_id=owner, granularity="by_model")
    assert summary["input_tokens"] == 300
    assert summary["cache_metrics_reported"] is False
    assert summary["buckets"][0]["cache_metrics_reported"] is False
    assert [row.cache_metrics_reported for row in repos.usage_repo.list_detail(user_id=owner)] == [
        True,
        False,
    ]
    run_migrations(pool)
    with pool.connect() as conn:
        assert conn.execute("SELECT version FROM _schema_version").fetchone()[0] == 39
        conn.execute("UPDATE _schema_version SET version=38")
    run_migrations(pool)
    assert [row.cache_metrics_reported for row in repos.usage_repo.list_detail(user_id=owner)] == [
        True,
        False,
    ]
    pool.close()
