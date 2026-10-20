"""Request inspection survives service recreation and enforces thread ownership."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any

import pytest

from octop.infra.db.migrate import run_migrations
from octop.infra.db.services import RepoBundle
from octop.infra.errors import OctopError
from octop.infra.execution.inspection import RequestInspectionService


class MemoryPool:
    dialect = "sqlite"

    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")

    @contextmanager
    def connect(self) -> Any:
        yield self.conn

    @contextmanager
    def transaction(self) -> Any:
        self.conn.execute("BEGIN")
        try:
            yield self.conn
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    def close(self) -> None:
        self.conn.close()


def test_requests_persist_updates_page_and_ownership() -> None:
    db = MemoryPool()
    try:
        run_migrations(db)
        repos = RepoBundle.from_pool(db)
        owner = repos.user_repo.create(username="owner", role="admin", password_hash="unused")
        other = repos.user_repo.create(username="other", role="user", password_hash="unused")
        repos.agent_repo.create(agent_id="expert", user_id=owner, name="Expert")
        repos.thread_repo.insert(
            thread_id="thread",
            agent_id="expert",
            user_id=owner,
            channel_type="dashboard",
            session_key="test",
        )
        service = RequestInspectionService(repos)
        event = {
            "request_id": "request-a",
            "thread_id": "thread",
            "owner_user_id": owner,
            "created_at": 1,
            "status": "started",
            "transformation": {
                "kind": "summarization",
                "before_estimated_tokens": 200,
                "after_estimated_tokens": 25,
            },
            "components": [
                {"kind": "user", "estimated_tokens": 25, "content": "actual user input"}
            ],
        }
        service.record("expert", event)
        service.record(
            "expert",
            {
                **event,
                "status": "completed",
                "actual_usage": {"input_tokens": 30, "output_tokens": 2},
            },
        )
        restored = RequestInspectionService(repos)
        history = restored.list(owner, "expert", "thread", before=None, limit=1)
        assert len(history["requests"]) == 1
        assert history["requests"][0]["status"] == "completed"
        assert history["requests"][0]["composition"] == {"user": 25}
        assert history["requests"][0]["transformation"]["before_estimated_tokens"] == 200
        from octop.api.routers.chat.inspection import RequestSnapshotOut

        response = RequestSnapshotOut.model_validate(
            {
                **history["requests"][0],
                "estimated_input_tokens": 25,
            }
        )
        assert response.transformation["after_estimated_tokens"] == 25
        assert "components" not in history["requests"][0]
        assert (
            restored.get(owner, "expert", "thread", "request-a")["components"][0]["content"]
            == "actual user input"
        )
        restored.record("expert", {**event, "request_id": "request-b", "created_at": 2})
        page = restored.list(owner, "expert", "thread", before=None, limit=1)
        assert page["has_more"]
        assert page["requests"][0]["request_id"] == "request-b"
        assert (
            restored.list(owner, "expert", "thread", before=page["next_before"], limit=1)[
                "requests"
            ][0]["request_id"]
            == "request-a"
        )
        with pytest.raises(OctopError):
            restored.get(other, "expert", "thread", "request-a")
        with pytest.raises(OctopError):
            restored.get(owner, "another-expert", "thread", "request-a")
        restored.record(
            "expert",
            {
                **event,
                "request_id": "request-bounded",
                "estimated_input_tokens": 100,
                "estimated_tokens_by_kind": {"user": 70, "tool_schema": 30},
                "component_count": 5002,
                "component_counts": {"user": 5001, "tool_schema": 1},
                "components_truncated": True,
                "omitted_component_count": 4746,
                "metadata_truncated": True,
            },
        )
        bounded = restored.list(owner, "expert", "thread", before=None, limit=1)["requests"][0]
        assert bounded["composition"] == {"user": 70, "tool_schema": 30}
        response = RequestSnapshotOut.model_validate(bounded)
        assert response.component_count == 5002
        assert response.components_truncated and response.metadata_truncated
        assert response.omitted_component_count == 4746
    finally:
        db.close()


def test_folded_execution_schema_reconciles_existing_watermark() -> None:
    db = MemoryPool()
    try:
        run_migrations(db)
        db.conn.execute("DROP TABLE request_snapshots")
        db.conn.execute("DROP TABLE thread_execution_settings")
        run_migrations(db)
        assert db.conn.execute("SELECT version FROM _schema_version").fetchone()[0] == 32
        assert db.conn.execute("SELECT COUNT(*) FROM request_snapshots").fetchone()[0] == 0
        assert db.conn.execute("SELECT COUNT(*) FROM thread_execution_settings").fetchone()[0] == 0
    finally:
        db.close()
