"""Authorize and retain final model requests without a running expert."""

from __future__ import annotations

from typing import Any

from octop.infra.db.repos.request_snapshots import RequestSnapshotRepo
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.execution.events import RunInspectionService


class RequestInspectionService:
    def __init__(self, repos: RepoBundle) -> None:
        self.repos = repos
        self.snapshots = RequestSnapshotRepo(repos.db)

    def _thread(self, owner: int, agent_id: str, thread_id: str) -> None:
        row = self.repos.thread_repo.get(thread_id)
        if row is None or row.user_id != owner or row.agent_id != agent_id:
            raise OctopError(ErrorCode.NOT_FOUND, "request history unavailable")

    def record(self, agent_id: str, snapshot: dict[str, Any]) -> None:
        thread_id = str(snapshot.get("thread_id") or "")
        if not thread_id:
            return
        owner = int(snapshot.get("owner_user_id") or 0)
        self._thread(owner, agent_id, thread_id)
        self.snapshots.save(
            owner, agent_id, thread_id, {**snapshot, "agent_id": agent_id, "owner_user_id": owner}
        )
        RunInspectionService(self.repos).request_receipt(agent_id, snapshot)

    def list(
        self, owner: int, agent_id: str, thread_id: str, *, before: int | None, limit: int
    ) -> dict[str, Any]:
        self._thread(owner, agent_id, thread_id)
        rows = self.snapshots.list(owner, agent_id, thread_id, before=before, limit=limit + 1)
        page = rows[:limit]
        items = [{key: value for key, value in row.items() if key != "components"} for row in page]
        for item, row in zip(items, page, strict=True):
            totals: dict[str, int] = dict(row.get("estimated_tokens_by_kind") or {})
            if not totals:
                for component in row.get("components", []):
                    kind = component["kind"]
                    totals[kind] = totals.get(kind, 0) + component["estimated_tokens"]
            item["composition"] = totals
        return {
            "requests": items,
            "has_more": len(rows) > limit,
            "next_before": page[-1]["seq"] if len(rows) > limit else None,
        }

    def get(self, owner: int, agent_id: str, thread_id: str, request_id: str) -> dict[str, Any]:
        self._thread(owner, agent_id, thread_id)
        row = self.snapshots.get(owner, agent_id, thread_id, request_id)
        if row is None:
            raise OctopError(ErrorCode.NOT_FOUND, "request snapshot unavailable")
        return row
