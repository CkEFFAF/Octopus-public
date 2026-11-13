from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.users import UserRepo
from octop.infra.db.repos.workflow_graphs import WorkflowGraphRepo


@pytest.fixture
def storage(tmp_path):
    pool = SqlitePool(tmp_path / "workflows.sqlite")
    run_migrations(pool)
    owner = UserRepo(pool).create(username="owner", password_hash="unused", role="user")
    other = UserRepo(pool).create(username="other", password_hash="unused", role="user")
    yield WorkflowGraphRepo(pool), owner, other
    pool.close()


def publish(repo, owner, graph_id="daily"):
    assert repo.save(owner, graph_id, 0, "Daily", json.dumps({"name": "Daily"}))
    assert repo.publish(owner, graph_id, 1, None)


def start(repo, owner, run_id="run", kind="entry", key="once"):
    return repo.create_run(
        owner=owner,
        graph_id="daily",
        version=1,
        run_id=run_id,
        key=key,
        fingerprint="same-input",
        initial="{}",
        max_steps=100,
        deadline=time.time() + 3600,
        entry={"id": run_id + "-entry", "node_id": "entry", "kind": kind, "token_json": "{}"},
    )


def test_unknown_and_superseded_submissions_keep_their_capacity_reservation(storage):
    repo, owner, _ = storage
    publish(repo, owner)
    for i in range(5):
        start(repo, owner, f"run{i}", kind="script", key=str(i))
    for i in range(4):
        assert repo.claim(owner, f"run{i}-entry", "worker", time.time())
        assert repo.fail(
            owner, f"run{i}-entry", "running", "lost response", unknown=True, worker="worker"
        )
    assert not repo.claim(owner, "run4-entry", "worker", time.time())
    old = repo.activation(owner, "run0-entry")
    replacement = {
        "id": "replacement",
        "node_id": "entry",
        "kind": "script",
        "token_json": old["token_json"],
    }
    assert repo.retry(owner, "run0-entry", replacement)
    assert not repo.claim(owner, "replacement", "worker", time.time())
    repo.release_capacity(owner, "run0-entry")
    assert repo.claim(owner, "replacement", "worker", time.time())


def test_migration_is_applied_and_definitions_are_owner_scoped(storage):
    repo, owner, other = storage
    with repo.db.connect() as conn:
        assert conn.execute("SELECT version FROM _schema_version").fetchone()[0] == 41
        names = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "workflow_graphs",
            "workflow_graph_versions",
            "workflow_runs",
            "workflow_activations",
            "workflow_admission",
        } <= names
    publish(repo, owner)
    assert repo.get(other, "daily") is None
    assert repo.version(other, "daily", 1) is None
    assert repo.list_graphs(other, 20, 0) == ([], 0)
    assert not repo.save(owner, "missing", 7, "Bad", "{}")
    assert repo.get(owner, "missing") is None


def test_revision_conflicts_and_immutable_published_version(storage):
    repo, owner, _ = storage
    publish(repo, owner)
    assert repo.save(owner, "daily", 1, "Changed", '{"name":"Changed"}')
    assert not repo.save(owner, "daily", 1, "Lost update", "{}")
    assert repo.version(owner, "daily", 1)["definition_json"] == '{"name": "Daily"}'
    assert repo.get(owner, "daily")["published_revision"] == 1
    assert repo.publish(owner, "daily", 2, None)
    assert repo.version(owner, "daily", 2)["definition_json"] == '{"name":"Changed"}'


def test_start_retry_does_not_duplicate_runs_or_change_pinned_version(storage):
    repo, owner, other = storage
    publish(repo, owner)
    assert start(repo, owner) == ("run", True)
    assert start(repo, owner, run_id="duplicate") == ("run", False)
    assert repo.list_runs(owner, "daily", 20, 0)[1] == 1
    assert repo.run(other, "run") is None
    assert repo.activations(other, "run") == []
    assert repo.save(owner, "daily", 1, "New", '{"name":"New"}')
    assert repo.publish(owner, "daily", 2, None)
    assert repo.run(owner, "run")["version"] == 1
    assert start(repo, owner, run_id="retry") == ("run", False)


def test_claim_is_atomic_and_admission_counts_outstanding_jobs(storage):
    repo, owner, _ = storage
    publish(repo, owner)
    start(repo, owner, kind="agent")
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda worker: repo.claim(owner, "run-entry", worker, time.time()), ["a", "b"]
            )
        )
    assert sorted(results) == [False, True]
    assert repo.run(owner, "run")["steps"] == 1
    assert not repo.renew(owner, "run-entry", "different-worker", time.time())
    for i in range(1, 5):
        start(repo, owner, run_id=f"run{i}", kind="script", key=f"once-{i}")
        assert repo.claim(owner, f"run{i}-entry", "worker", time.time()) == (i < 4)
    with repo.db.transaction() as conn:
        conn.execute("UPDATE workflow_activations SET status='waiting_job' WHERE id='run1-entry'")
    assert not repo.claim(owner, "run4-entry", "worker", time.time())


def test_budget_pause_keeps_the_queued_activation(storage):
    repo, owner, _ = storage
    publish(repo, owner)
    start(repo, owner)
    with repo.db.transaction() as conn:
        conn.execute("UPDATE workflow_runs SET deadline=? WHERE id='run'", (time.time() - 1,))
    assert not repo.claim(owner, "run-entry", "worker", time.time())
    assert repo.run(owner, "run")["status"] == "paused"
    assert repo.activation(owner, "run-entry")["status"] == "ready"


def test_completion_is_once_and_pause_retains_the_next_step(storage):
    repo, owner, _ = storage
    publish(repo, owner)
    start(repo, owner)
    assert repo.claim(owner, "run-entry", "worker", time.time())
    child = {
        "id": "end",
        "node_id": "end",
        "kind": "end",
        "token_json": "{}",
        "parent_id": "run-entry",
    }
    assert repo.control(owner, "run", "pause")
    assert not repo.finish(
        owner, "run-entry", "running", worker="other", output="{}", after="{}", children=[child]
    )
    assert repo.finish(
        owner, "run-entry", "running", worker="worker", output="{}", after="{}", children=[child]
    )
    assert not repo.finish(
        owner, "run-entry", "running", worker="worker", output="{}", after="{}", children=[child]
    )
    assert len(repo.activations(owner, "run")) == 2
    assert repo.run(owner, "run")["status"] == "paused"
    assert not repo.ready()
    assert repo.control(owner, "run", "resume")
    assert [row["id"] for row in repo.ready()] == ["end"]
    assert repo.claim(owner, "end", "worker", time.time())
    assert repo.finish(
        owner, "end", "running", worker="worker", output="{}", after="{}", children=[]
    )
    assert repo.run(owner, "run")["status"] == "succeeded"


def test_cancel_waits_for_accepted_jobs_and_never_dispatches_successors(storage):
    repo, owner, _ = storage
    publish(repo, owner)
    start(repo, owner, kind="script")
    assert repo.claim(owner, "run-entry", "worker", time.time())
    assert repo.update_activation(
        owner,
        "run-entry",
        "running",
        {"status": "waiting_job", "lease_until": None},
        worker="worker",
    )
    assert repo.control(owner, "run", "cancel")
    assert repo.run(owner, "run")["status"] == "cancelling"
    child = {"id": "should-not-run", "node_id": "end", "kind": "end", "token_json": "{}"}
    assert repo.finish(owner, "run-entry", "waiting_job", output="{}", after="{}", children=[child])
    assert repo.activation(owner, "should-not-run") is None
    assert repo.run(owner, "run")["status"] == "cancelled"


def test_expired_worker_cannot_complete_and_retry_is_a_distinct_activation(storage):
    repo, owner, _ = storage
    publish(repo, owner)
    start(repo, owner)
    assert repo.claim(owner, "run-entry", "old", time.time())
    assert repo.expire_leases(time.time() + 121) == 1
    assert repo.run(owner, "run")["status"] == "unknown"
    assert not repo.control(owner, "run", "resume")
    assert not repo.finish(
        owner, "run-entry", "running", worker="old", output="{}", after="{}", children=[]
    )
    replacement = {
        "id": "authorized-retry",
        "node_id": "entry",
        "kind": "entry",
        "token_json": "{}",
    }
    assert repo.retry(owner, "run-entry", replacement)
    assert repo.activation(owner, "run-entry")["status"] == "superseded"
    assert repo.claim(owner, "authorized-retry", "new", time.time())
    assert repo.record_evidence(owner, "run-entry", "old", '{"late_receipt":true}')
    assert repo.activation(owner, "run-entry")["status"] == "superseded"


def test_join_commits_successor_once_after_all_arrivals(storage):
    repo, owner, _ = storage
    publish(repo, owner)
    start(repo, owner)
    assert repo.claim(owner, "run-entry", "worker", time.time())
    branches = [
        {
            "id": f"join-{i}",
            "node_id": "join",
            "kind": "join",
            "token_json": "{}",
            "group_id": "fork",
            "branch_id": str(i),
        }
        for i in range(2)
    ]
    assert repo.finish(
        owner, "run-entry", "running", worker="worker", output="{}", after="{}", children=branches
    )
    for i in range(2):
        assert repo.claim(owner, f"join-{i}", "worker", time.time())
        arrivals = repo.arrive_join(owner, f"join-{i}", "worker")
        assert len(arrivals) == i + 1
    child = {"id": "joined-end", "node_id": "end", "kind": "end", "token_json": "{}"}
    assert repo.finish_join(
        owner, [row["id"] for row in arrivals], output="{}", after="{}", children=[child]
    )
    assert not repo.finish_join(
        owner, [row["id"] for row in arrivals], output="{}", after="{}", children=[child]
    )
    assert [row["id"] for row in repo.ready()] == ["joined-end"]
