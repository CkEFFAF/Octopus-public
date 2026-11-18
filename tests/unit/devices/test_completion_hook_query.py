"""Completion discovery preserves ownership and delivery semantics at scale."""

from pathlib import Path

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.agents import AgentRepo
from octop.infra.db.repos.run_events import RunEventRepo
from octop.infra.db.repos.threads import ThreadRepo
from octop.infra.db.repos.users import UserRepo


def test_completion_discovery_matches_only_owner_wake_hooks(tmp_path: Path) -> None:
    db = SqlitePool(tmp_path / "hooks.db")
    run_migrations(db)
    users = UserRepo(db)
    owner = users.create(username="owner", password_hash="unused", role="admin")
    other = users.create(username="other", password_hash="unused", role="user")
    AgentRepo(db).create(agent_id="expert", user_id=owner, name="Expert")
    ThreadRepo(db).insert(
        thread_id="origin",
        agent_id="expert",
        user_id=owner,
        channel_type="dashboard",
        session_key="origin",
    )
    repo = RunEventRepo(db)

    def job(name: str, *, notify: bool = True) -> None:
        repo.save(
            event_id=name,
            owner=owner,
            agent_id="expert",
            thread_id="origin",
            run_id=name,
            context_id="ctx",
            kind="job",
            status="completed",
            payload={"notify_on_exit": notify},
        )

    def hook(name: str, target: str, mode: str | None, user: int = owner) -> None:
        payload = {"job_event_id": target}
        if mode is not None:
            payload["delivery_mode"] = mode
        repo.save(
            event_id=name,
            owner=user,
            agent_id="expert",
            thread_id=None,
            run_id=name,
            context_id="ctx",
            kind="hook",
            status="completed",
            payload=payload,
        )

    for name in ("covered", "legacy", "foreign", "signal", "progress", "uncovered"):
        job(name)
    job("opted-out", notify=False)
    hook("wake1", "covered", "wake")
    hook("wake2", "covered", "wake")
    hook("legacy-hook", "legacy", None)
    hook("foreign-hook", "foreign", "wake", other)
    hook("signal-hook", "signal", "signal")
    hook("progress-hook", "progress", "progress")
    with db.transaction() as conn:
        conn.executemany(
            "INSERT INTO run_events(event_id,owner_user_id,run_id,created_at,updated_at,kind,status,payload_json) "
            "VALUES (?,?,?,0,0,'model','completed','{}')",
            [(f"model-{i}", owner, f"run-{i}") for i in range(1000)],
        )
    steps = 0

    def budget() -> int:
        nonlocal steps
        steps += 1
        return int(steps > 30)

    # Bound database work, not wall time: unrelated model receipts must not be
    # rescanned for each job. SQLite aborts after 30,000 virtual instructions.
    with db.connect() as conn:
        conn.set_progress_handler(budget, 1000)
        try:
            found = repo.jobs_without_completion_hook()
        finally:
            conn.set_progress_handler(None, 0)
    assert [row["event_id"] for row in found] == ["foreign", "signal", "progress", "uncovered"]
    assert [row["event_id"] for row in repo.jobs_without_completion_hook(limit=2)] == [
        "foreign",
        "signal",
    ]
    db.close()
