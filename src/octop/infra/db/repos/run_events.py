"""Run correlation and bounded receipt summaries; content stays in its own store."""

from __future__ import annotations

import builtins
import hashlib
import json
import time
from collections.abc import Sequence
from typing import Any

from octop.infra.db.pool import DatabasePool
from octop.infra.db.repos.conversation_metadata import (
    encoded,
    mark_metadata_dirty,
    record_semantic_event,
)


class RunEventRepo:
    def __init__(self, db: DatabasePool) -> None:
        self.db = db

    def save(
        self,
        *,
        event_id: str,
        owner: int,
        agent_id: str | None,
        thread_id: str | None,
        run_id: str,
        context_id: str | None,
        kind: str,
        status: str,
        payload: dict[str, Any],
        created_at: float | None = None,
        replace: bool = True,
        work_item_id: str | None = None,
    ) -> None:
        now = time.time()
        with self.db.transaction() as conn:
            previous = conn.execute(
                "SELECT status,payload_json FROM run_events WHERE event_id=? AND owner_user_id=?",
                (event_id, owner),
            ).fetchone()
            saved = conn.execute(
                "INSERT INTO run_events(event_id, owner_user_id, agent_id, thread_id, run_id, context_id, created_at, updated_at, kind, status, payload_json, work_item_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(event_id) "
                + (
                    "DO UPDATE SET updated_at = excluded.updated_at, status = excluded.status, payload_json = excluded.payload_json, "
                    "work_item_id = COALESCE(excluded.work_item_id, run_events.work_item_id) "
                    "WHERE run_events.owner_user_id = excluded.owner_user_id AND run_events.run_id = excluded.run_id"
                    if replace
                    else "DO NOTHING"
                ),
                (
                    event_id,
                    owner,
                    agent_id,
                    thread_id,
                    run_id,
                    context_id,
                    created_at or now,
                    now,
                    kind,
                    status,
                    json.dumps(payload, ensure_ascii=False),
                    work_item_id,
                ),
            ).rowcount
            if saved:
                self._metadata_event(
                    conn, thread_id, event_id, kind, status, payload, previous, now
                )

    @staticmethod
    def _metadata_event(
        conn: Any,
        thread: str | None,
        event_id: str,
        kind: str,
        status: str,
        payload: dict[str, Any],
        previous: Any,
        now: float,
    ) -> None:
        if not thread or kind not in {"tool", "job", "dispatch", "device", "workflow"}:
            return
        # Receipt transitions, not poll timestamps or stdout, affect semantic progress.
        facts = {
            key: payload[key]
            for key in (
                "name",
                "action",
                "job_id",
                "task_outcome",
                "error_code",
                "task_id",
                "invocation_id",
            )
            if key in payload and isinstance(payload[key], (str, int, bool))
        }
        receipt = payload.get("receipt")
        receipt = receipt if isinstance(receipt, dict) else {}
        facts.update({key: receipt[key] for key in ("returncode", "status") if key in receipt})
        old_payload = json.loads(previous["payload_json"]) if previous else {}
        if kind == "workflow":
            facts["version"] = payload.get("version", 0)
        old_receipt = old_payload.get("receipt")
        old_receipt = old_receipt if isinstance(old_receipt, dict) else {}
        if (
            previous
            and previous["status"] == status
            and all(
                old_payload.get(key) == payload.get(key)
                for key in facts
                if key not in {"returncode", "status"}
            )
            and all(old_receipt.get(key) == receipt.get(key) for key in ("returncode", "status"))
        ):
            return
        key = hashlib.sha256(encoded([status, facts]).encode()).hexdigest()[:20]
        record_semantic_event(
            conn,
            thread,
            f"run:{event_id}:{key}",
            "execution",
            {
                "status": status,
                "facts": facts,
                "source_refs": [{"kind": "run", "id": event_id}],
                "author_kind": "runtime",
            },
            now,
        )
        mark_metadata_dirty(conn, thread, "activity")

    def get(self, owner: int, event_id: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM run_events WHERE owner_user_id = ? AND event_id = ?",
                (owner, event_id),
            ).fetchone()
        return self._public(row) if row is not None else None

    def active(self, owner: int, agent: str, thread: str, limit: int = 200) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM run_events WHERE owner_user_id=? AND agent_id=? AND thread_id=? AND kind IN ('dispatch','job','tool','device') AND status IN ('running','started','accepted','waiting') ORDER BY updated_at DESC,id DESC LIMIT ?",
                (owner, agent, thread, limit),
            ).fetchall()
        return [self._public(row) for row in rows]

    def sidebar_jobs(self, owner: int, agent: str) -> list[dict[str, Any]]:
        """Bounded account/expert observations without command or log bodies."""
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT event_id,thread_id,status,updated_at,payload_json FROM run_events "
                "WHERE owner_user_id=? AND agent_id=? AND kind='job' "
                "AND status IN ('running','started','accepted','waiting') ORDER BY updated_at DESC LIMIT 200",
                (owner, agent),
            ).fetchall()
        progress = self.job_progress(owner, [r["event_id"] for r in rows])
        result = []
        for r in rows:
            payload = json.loads(r["payload_json"])
            result.append(
                {
                    "id": r["event_id"],
                    "thread_id": r["thread_id"],
                    "status": r["status"],
                    "updated_at": r["updated_at"],
                    "stale": time.time() - r["updated_at"] > 45,
                    "name": str(payload.get("program") or payload.get("job_id") or r["event_id"])[
                        :100
                    ],
                    "title": payload.get("title"),
                    "job_kind": payload.get("job_kind"),
                    "subject": payload.get("subject"),
                    "progress": progress.get(r["event_id"]),
                }
            )
        return result

    def background_page(
        self,
        owner: int,
        agent: str,
        *,
        lifecycle: str,
        thread: str | None,
        offset: int,
        limit: int,
    ) -> dict[str, Any]:
        cutoff = time.time() - 45
        sql = (
            "SELECT r.event_id AS id,r.thread_id,t.title,r.status,r.updated_at,r.payload_json,"
            "CASE WHEN r.status IN ('running','started','accepted','waiting') "
            "THEN CASE WHEN r.updated_at>=? THEN 'active' ELSE 'inactive' END "
            "WHEN r.status='completed' THEN 'completed' WHEN r.status='failed' THEN 'failed' "
            "ELSE 'inactive' END AS lifecycle "
            "FROM run_events r JOIN threads t ON t.thread_id=r.thread_id "
            "AND t.user_id=r.owner_user_id AND t.agent_id=r.agent_id "
            "WHERE r.owner_user_id=? AND r.agent_id=? AND r.kind='job' "
            "AND "
            + ("" if lifecycle == "archived" else "NOT ")
            + "EXISTS (SELECT 1 FROM task_history_archives a WHERE a.owner_user_id=r.owner_user_id "
            "AND a.source='receipt' AND a.source_id=r.event_id AND a.source_updated_at=r.updated_at)"
        )
        values: list[Any] = [cutoff, owner, agent]
        if thread:
            sql += " AND r.thread_id=?"
            values.append(thread)
        with self.db.connect() as conn:
            counts = {
                r["lifecycle"]: r["n"]
                for r in conn.execute(
                    f"SELECT lifecycle,COUNT(*) AS n FROM ({sql}) jobs GROUP BY lifecycle", values
                ).fetchall()
            }
            selected = f"SELECT * FROM ({sql}) jobs"
            if lifecycle not in {"all", "archived"}:
                selected += " WHERE lifecycle=?"
                values.append(lifecycle)
            total = (
                sum(counts.values())
                if lifecycle in {"all", "archived"}
                else counts.get(lifecycle, 0)
            )
            rows = conn.execute(
                selected + " ORDER BY updated_at DESC,id LIMIT ? OFFSET ?", [*values, limit, offset]
            ).fetchall()
        progress = self.job_progress(owner, [r["id"] for r in rows])
        items = []
        for row in rows:
            item = dict(row)
            payload = json.loads(item.pop("payload_json"))
            items.append(
                {
                    **item,
                    "job_title": payload.get("title"),
                    "name": payload.get("program"),
                    "job_kind": payload.get("job_kind"),
                    "subject": payload.get("subject"),
                    "progress": progress.get(row["id"]),
                }
            )
        return {
            "items": items,
            "counts": counts,
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    def due_jobs(self, before: float, *, limit: int = 64) -> list[dict[str, Any]]:
        """Recover pending observations after restart; oldest checks run first."""
        with self.db.connect() as conn:
            rows = conn.execute(
                "WITH candidates AS (SELECT e.*,COALESCE(c.target_kind,'missing') AS poll_kind, "
                "CASE WHEN c.context_id IS NULL THEN e.context_id "
                "ELSE COALESCE(c.device_id,'local') END AS poll_target "
                "FROM run_events e LEFT JOIN execution_contexts c ON c.context_id=e.context_id "
                "AND c.owner_user_id=e.owner_user_id WHERE e.kind='job' "
                "AND e.status NOT IN ('completed','failed','cancelled') AND e.updated_at<?), "
                "due AS (SELECT *,ROW_NUMBER() OVER (PARTITION BY owner_user_id,poll_kind,poll_target "
                "ORDER BY updated_at,id) AS poll_rank FROM candidates) "
                "SELECT * FROM due ORDER BY poll_rank,updated_at,id LIMIT ?",
                (before, limit),
            ).fetchall()
        return [
            {
                **self._public(row),
                "owner_user_id": row["owner_user_id"],
                "_poll_target": (int(row["owner_user_id"]), row["poll_kind"], row["poll_target"]),
            }
            for row in rows
        ]

    def wakeup_hook(self, event_id: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM run_events WHERE event_id=? AND kind='hook'", (event_id,)
            ).fetchone()
        return {**self._public(row), "owner_user_id": row["owner_user_id"]} if row else None

    def recover_wakeup_deliveries(self) -> None:
        """An interrupted model call has an uncertain outcome, never silently replay it."""
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE run_events SET status='unknown',updated_at=? WHERE kind='hook' AND status='running'",
                (time.time(),),
            )

    def pending_wakeup_hooks(self, limit: int = 128) -> list[dict[str, Any]]:
        if self.db.dialect == "postgresql":
            job = "h.payload_json::jsonb->>'job_event_id'"
            expiry = "(h.payload_json::jsonb->>'expires_at')::double precision"
            mode = "h.payload_json::jsonb->>'delivery_mode'"
        else:
            job = "json_extract(h.payload_json,'$.job_event_id')"
            expiry = "json_extract(h.payload_json,'$.expires_at')"
            mode = "json_extract(h.payload_json,'$.delivery_mode')"
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT h.* FROM run_events h WHERE h.kind='hook' AND COALESCE(({mode}),'wake') <> 'signal' AND (h.status='queued' OR (h.status='waiting' AND ({expiry}<=? OR EXISTS(SELECT 1 FROM run_events j WHERE j.owner_user_id=h.owner_user_id AND j.event_id=({job}) AND j.kind='job' AND j.status IN ('completed','failed','cancelled'))))) ORDER BY CASE WHEN h.status='queued' THEN 0 ELSE 1 END,h.updated_at,h.id LIMIT ?",
                (time.time(), limit),
            ).fetchall()
        return [{**self._public(row), "owner_user_id": row["owner_user_id"]} for row in rows]

    def jobs_without_completion_hook(self, limit: int = 64) -> list[dict[str, Any]]:
        if self.db.dialect == "postgresql":
            opted = "j.payload_json::jsonb->>'notify_on_exit'='true'"
            reference = "h.payload_json::jsonb->>'job_event_id'"
            mode = "h.payload_json::jsonb->>'delivery_mode'"
        else:
            opted = "json_extract(j.payload_json,'$.notify_on_exit')=1"
            reference = "json_extract(h.payload_json,'$.job_event_id')"
            mode = "json_extract(h.payload_json,'$.delivery_mode')"
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT j.* FROM run_events j WHERE j.kind='job' AND j.agent_id IS NOT NULL AND j.thread_id IS NOT NULL AND j.context_id IS NOT NULL AND {opted} AND NOT EXISTS(SELECT 1 FROM run_events h WHERE h.kind='hook' AND h.owner_user_id=j.owner_user_id AND ({reference})=j.event_id AND COALESCE({mode},'wake')='wake') ORDER BY j.id LIMIT ?",
                (limit,),
            ).fetchall()
        return [{**self._public(row), "owner_user_id": row["owner_user_id"]} for row in rows]

    def jobs_without_progress_binding(self, limit: int = 64) -> list[dict[str, Any]]:
        if self.db.dialect == "postgresql":
            hook = "j.payload_json::jsonb->>'progress_hook_id'"
            reference = "h.payload_json::jsonb->>'job_event_id'"
        else:
            hook = "json_extract(j.payload_json,'$.progress_hook_id')"
            reference = "json_extract(h.payload_json,'$.job_event_id')"
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT j.* FROM run_events j JOIN run_events h ON h.event_id=({hook}) AND h.owner_user_id=j.owner_user_id AND h.agent_id=j.agent_id AND h.thread_id=j.thread_id WHERE j.kind='job' AND h.kind='hook' AND h.status IN ('waiting','completed') AND ({reference}) IS NULL ORDER BY j.id LIMIT ?",
                (limit,),
            ).fetchall()
        return [{**self._public(row), "owner_user_id": row["owner_user_id"]} for row in rows]

    def job_progress(self, owner: int, event_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not event_ids:
            return {}
        if self.db.dialect == "postgresql":
            reference = "h.payload_json::jsonb->>'job_event_id'"
        else:
            reference = "json_extract(h.payload_json,'$.job_event_id')"
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT j.event_id,h.payload_json FROM run_events h JOIN run_events j ON j.event_id=({reference}) AND j.owner_user_id=h.owner_user_id AND j.agent_id=h.agent_id AND j.thread_id=h.thread_id WHERE h.owner_user_id=? AND h.kind='hook' AND j.kind='job' AND j.event_id IN ({','.join('?' for _ in event_ids)})",
                [owner, *event_ids],
            ).fetchall()
        result = {}
        for row in rows:
            payload = json.loads(row["payload_json"])
            if payload.get("delivery_mode") == "progress" and isinstance(
                payload.get("progress"), dict
            ):
                result[row["event_id"]] = payload["progress"]
        return result

    def compare_payload(
        self,
        owner: int,
        event_id: str,
        previous: dict[str, Any],
        payload: dict[str, Any],
        status: str,
        *,
        expected_status: str | None = None,
    ) -> bool:
        """Atomically advance a workflow, including across control-center workers."""
        with self.db.transaction() as conn:
            original = conn.execute(
                "SELECT thread_id,kind,status,payload_json FROM run_events WHERE owner_user_id=? AND event_id=?",
                (owner, event_id),
            ).fetchone()
            result = conn.execute(
                "UPDATE run_events SET payload_json = ?, status = ?, updated_at = ? "
                "WHERE owner_user_id = ? AND event_id = ? AND payload_json = ?"
                + (" AND status = ?" if expected_status is not None else ""),
                [
                    json.dumps(payload, ensure_ascii=False),
                    status,
                    time.time(),
                    owner,
                    event_id,
                    json.dumps(previous, ensure_ascii=False),
                    *([expected_status] if expected_status is not None else []),
                ],
            )
            if result.rowcount and original:
                self._metadata_event(
                    conn,
                    original["thread_id"],
                    event_id,
                    original["kind"],
                    status,
                    payload,
                    original,
                    time.time(),
                )
        return bool(result.rowcount)

    def list(
        self,
        owner: int,
        agent_id: str,
        thread_id: str,
        *,
        before: int | None = None,
        run_id: str | None = None,
        limit: int = 100,
        kind: str | None = None,
        include_archived: bool = True,
    ) -> builtins.list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM run_events WHERE owner_user_id = ? AND agent_id = ? AND thread_id = ? "
                + ("AND id < ? " if before is not None else "")
                + ("AND run_id = ? " if run_id is not None else "")
                + ("AND kind = ? " if kind is not None else "")
                + (
                    "AND NOT EXISTS (SELECT 1 FROM task_history_archives a WHERE "
                    "a.owner_user_id=run_events.owner_user_id AND a.source='receipt' "
                    "AND a.source_id=run_events.event_id AND a.source_updated_at=run_events.updated_at) "
                    if not include_archived
                    else ""
                )
                + "ORDER BY id DESC LIMIT ?",
                [
                    owner,
                    agent_id,
                    thread_id,
                    *([before] if before is not None else []),
                    *([run_id] if run_id is not None else []),
                    *([kind] if kind is not None else []),
                    limit,
                ],
            ).fetchall()
        return [self._public(row) for row in rows]

    def get_many(self, owner: int, identities: Sequence[str]) -> dict[str, dict[str, Any]]:
        if not identities:
            return {}
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM run_events WHERE owner_user_id=? AND event_id IN ("
                + ",".join("?" for _ in identities)
                + ")",
                [owner, *identities],
            ).fetchall()
        return {row["event_id"]: self._public(row) for row in rows}

    def list_for_work_item(
        self,
        owner: int,
        work_item_id: str,
        *,
        before: int | None = None,
        limit: int = 100,
        kind: str | None = None,
    ) -> builtins.list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM run_events WHERE owner_user_id = ? AND work_item_id = ? "
                + ("AND id < ? " if before is not None else "")
                + ("AND kind = ? " if kind is not None else "")
                + "ORDER BY id DESC LIMIT ?",
                [
                    owner,
                    work_item_id,
                    *([before] if before is not None else []),
                    *([kind] if kind is not None else []),
                    limit,
                ],
            ).fetchall()
        return [self._public(row) for row in rows]

    @staticmethod
    def _public(row: Any) -> dict[str, Any]:
        keys = [
            "event_id",
            "agent_id",
            "thread_id",
            "run_id",
            "context_id",
            "kind",
            "status",
            "created_at",
            "updated_at",
        ]
        # work_item_id exists after migration 036; tolerate older rows/tests.
        try:
            work_item_id = row["work_item_id"]
        except (KeyError, IndexError):
            work_item_id = None
        return {
            "seq": row["id"],
            **{key: row[key] for key in keys},
            "work_item_id": work_item_id,
            "payload": json.loads(row["payload_json"]),
        }
