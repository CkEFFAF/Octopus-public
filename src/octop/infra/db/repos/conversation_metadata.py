"""Conversation projections, source revisions and leased auxiliary model jobs."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Literal

from octop.infra.db.pool import DatabasePool
from octop.infra.utils.ulid import new_ulid


def encoded(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def settings_key(owner: int) -> str:
    return f"conversation_metadata.user.{owner}"


def record_semantic_event(
    conn: Any,
    thread: str,
    source: str,
    kind: str,
    payload: dict[str, Any],
    occurred_at: float,
) -> None:
    identity = "cve_" + hashlib.sha256(f"{thread}:{source}".encode()).hexdigest()[:32]
    conn.execute(
        "INSERT INTO thread_semantic_events(event_id,thread_id,source_key,kind,occurred_at,recorded_at,payload_json) "
        "SELECT ?,thread_id,?,?,?,?,? FROM threads WHERE thread_id=? "
        "ON CONFLICT(thread_id,source_key) DO UPDATE SET payload_json=excluded.payload_json",
        (identity, source, kind, occurred_at, time.time(), encoded(payload), thread),
    )


def mark_metadata_dirty(
    conn: Any, thread: str | None, domain: Literal["message", "activity", "artifact"]
) -> None:
    """Called inside the source transaction, including updates without new messages."""
    if not thread:
        return
    column = f"{domain}_revision"
    conn.execute(
        f"UPDATE thread_metadata SET source_revision=source_revision+1,{column}={column}+1,dirty=1 WHERE thread_id=?",
        (thread,),
    )
    now = time.time()
    conn.execute(
        "INSERT INTO thread_metadata_jobs(job_id,dedup_key,owner_user_id,agent_id,thread_id,kind,not_before,created_at,updated_at) "
        "SELECT ?,?,t.user_id,t.agent_id,t.thread_id,'auto',?,?,? FROM threads t "
        "JOIN thread_metadata m ON m.thread_id=t.thread_id WHERE t.thread_id=? AND m.auto_enrolled=1 "
        "ON CONFLICT(dedup_key) DO UPDATE SET "
        "status=CASE WHEN thread_metadata_jobs.status='running' THEN 'running' ELSE 'queued' END,"
        "attempts=CASE WHEN thread_metadata_jobs.status='running' THEN thread_metadata_jobs.attempts ELSE 0 END,"
        "not_before=excluded.not_before,updated_at=excluded.updated_at,error_code=''",
        (f"auto:{thread}", f"auto:{thread}", now + 5, now, now, thread),
    )


class ConversationMetadataRepo:
    def __init__(self, db: DatabasePool) -> None:
        self.db = db

    def get(self, thread: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM thread_metadata WHERE thread_id=?", (thread,)
            ).fetchone()
        if row is None:
            return None
        return {
            **dict(row),
            "snapshot": json.loads(row["snapshot_json"]),
            "manual": json.loads(row["manual_json"]),
        }

    def settings(self, owner: int) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key=?", (settings_key(owner),)
            ).fetchone()
        return json.loads(row["value"]) if row else {}

    def save_settings(self, owner: int, expected: int, value: dict[str, Any]) -> bool:
        with self.db.transaction() as conn:
            if self.db.dialect == "postgresql":
                conn.execute(
                    "SELECT id FROM users WHERE id=? FOR NO KEY UPDATE", (owner,)
                ).fetchone()
            row = conn.execute(
                "SELECT value FROM settings WHERE key=?", (settings_key(owner),)
            ).fetchone()
            current = json.loads(row["value"]) if row else {}
            if int(current.get("revision", 0)) != expected:
                return False
            conn.execute(
                "INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (settings_key(owner), encoded({**value, "revision": expected + 1})),
            )
        return True

    def enroll(self, thread: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE thread_metadata SET auto_enrolled=1 WHERE thread_id=?", (thread,))

    @staticmethod
    def _history_batch(conn: Any, owner: int, batch: str | None = None) -> dict[str, Any] | None:
        if batch is None:
            latest = conn.execute(
                "SELECT request_json FROM thread_metadata_jobs WHERE owner_user_id=? "
                "AND dedup_key LIKE 'batch:%' ORDER BY id DESC LIMIT 1",
                (owner,),
            ).fetchone()
            if latest is None:
                return None
            batch = json.loads(latest["request_json"])["batch_id"]
        rows = conn.execute(
            "SELECT status,COUNT(*) AS count FROM thread_metadata_jobs "
            "WHERE owner_user_id=? AND request_json=? GROUP BY status",
            (owner, encoded({"batch_id": batch})),
        ).fetchall()
        if not rows:
            return None
        counts = {row["status"]: row["count"] for row in rows}
        errors = conn.execute(
            "SELECT error_code,COUNT(*) AS count FROM thread_metadata_jobs "
            "WHERE owner_user_id=? AND request_json=? AND status='failed' "
            "GROUP BY error_code",
            (owner, encoded({"batch_id": batch})),
        ).fetchall()
        return {
            "batch_id": batch,
            "total": sum(counts.values()),
            "errors": {row["error_code"]: row["count"] for row in errors},
            "queued": counts.get("queued", 0) + counts.get("retry", 0),
            **{key: counts.get(key, 0) for key in ("running", "ready", "failed", "cancelled")},
        }

    def history_batch(self, owner: int) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            return self._history_batch(conn, owner)

    def start_history_batch(
        self, owner: int, command: str, agent: str | None, threads: list[str] | None
    ) -> dict[str, Any]:
        # One transaction snapshots the full account scope, without a recent-list cap.
        with self.db.transaction() as conn:
            if self.db.dialect == "postgresql":
                conn.execute(
                    "SELECT id FROM users WHERE id=? FOR NO KEY UPDATE", (owner,)
                ).fetchone()
            previous = self._history_batch(conn, owner, command)
            if previous:
                return previous
            active = conn.execute(
                "SELECT request_json FROM thread_metadata_jobs WHERE owner_user_id=? "
                "AND dedup_key LIKE 'batch:%' AND status IN ('queued','retry','running') "
                "ORDER BY id DESC LIMIT 1",
                (owner,),
            ).fetchone()
            if active:
                current = self._history_batch(
                    conn, owner, json.loads(active["request_json"])["batch_id"]
                )
                assert current is not None
                return current
            where = "t.user_id=? AND (a.user_id=? OR a.is_shared=1)"
            values: list[Any] = [owner, owner]
            if agent is not None:
                where += " AND t.agent_id=?"
                values.append(agent)
            if threads is not None:
                where += f" AND t.thread_id IN ({','.join('?' for _ in threads)})"
                values.extend(threads)
            now = time.time()
            prefix = f"batch:{owner}:{command}:"
            conn.execute(
                "INSERT INTO thread_metadata_jobs(job_id,dedup_key,owner_user_id,agent_id,thread_id,"
                "kind,request_json,created_at,updated_at) "
                "SELECT ? || t.thread_id,? || t.thread_id,t.user_id,t.agent_id,t.thread_id,'brief',?,?,? "
                f"FROM threads t JOIN agents a ON a.agent_id=t.agent_id WHERE {where} "
                "ON CONFLICT(dedup_key) DO NOTHING",
                (prefix, prefix, encoded({"batch_id": command}), now, now, *values),
            )
            conn.execute(
                "UPDATE thread_metadata SET auto_enrolled=1 WHERE thread_id IN "
                "(SELECT thread_id FROM thread_metadata_jobs WHERE owner_user_id=? AND request_json=?)",
                (owner, encoded({"batch_id": command})),
            )
            return self._history_batch(conn, owner, command) or {"batch_id": command, "total": 0}

    def record_fork(self, owner: int, thread: str, source: str) -> None:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT p.title FROM threads t JOIN threads p ON p.thread_id=? "
                "WHERE t.thread_id=? AND t.user_id=? AND p.user_id=t.user_id AND p.agent_id=t.agent_id",
                (source, thread, owner),
            ).fetchone()
            if row is None:
                return
            record_semantic_event(
                conn,
                thread,
                "fork:origin",
                "fork",
                {
                    "source_thread_id": source,
                    "source_title": row["title"],
                    "author_kind": "runtime",
                },
                time.time(),
            )
            mark_metadata_dirty(conn, thread, "activity")

    def archive_changed(self, thread: str, first_seq: int = 1) -> None:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT snapshot_json FROM thread_metadata WHERE thread_id=?", (thread,)
            ).fetchone()
            if row:
                snapshot = json.loads(row["snapshot_json"])
                coverage = snapshot.get("coverage", {})
                if int(coverage.get("archive_seq", 0)) >= first_seq:
                    # Resumed turns can revise already indexed documents, not just append.
                    # Rebuild derived prose from original sources; the previous brief may
                    # describe facts removed by the edit, even when its refs still exist.
                    snapshot = {
                        "objective_version": snapshot.get("objective_version", 1),
                        "coverage": {"archive_seq": 0, "complete": False},
                    }
                    conn.execute(
                        "UPDATE thread_metadata SET snapshot_json=?,generated_source_revision=-1 WHERE thread_id=?",
                        (encoded(snapshot), thread),
                    )
                    conn.execute(
                        "DELETE FROM thread_semantic_events WHERE thread_id=? AND source_key LIKE 'semantic:%'",
                        (thread,),
                    )
                    conn.execute("DELETE FROM thread_digests WHERE thread_id=?", (thread,))
            mark_metadata_dirty(conn, thread, "message")

    def patch_manual(self, thread: str, expected: int, manual: dict[str, Any]) -> bool:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT manual_json FROM thread_metadata WHERE thread_id=? AND revision=?",
                (thread, expected),
            ).fetchone()
            if row is None:
                return False
            merged = json.loads(row["manual_json"])
            merged.update(manual)
            merged = {key: value for key, value in merged.items() if value is not None}
            changed = conn.execute(
                "UPDATE thread_metadata SET manual_json=?,revision=revision+1 WHERE thread_id=? AND revision=?",
                (encoded(merged), thread, expected),
            ).rowcount
            if changed:
                record_semantic_event(
                    conn,
                    thread,
                    f"manual:{expected + 1}",
                    "manual",
                    {"changes": manual, "author_kind": "user"},
                    time.time(),
                )
                mark_metadata_dirty(conn, thread, "activity")
        return bool(changed)

    def enqueue(
        self, owner: int, agent: str, thread: str, kind: str, request: dict[str, Any], dedup: str
    ) -> dict[str, Any]:
        now = time.time()
        identity = new_ulid()
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO thread_metadata_jobs(job_id,dedup_key,owner_user_id,agent_id,thread_id,kind,request_json,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(dedup_key) DO NOTHING",
                (identity, dedup, owner, agent, thread, kind, encoded(request), now, now),
            )
            if kind == "digest":
                # A new explicit request retries a failed cached-range job; polling never does.
                conn.execute(
                    "UPDATE thread_metadata_jobs SET status='queued',attempts=0,error_code='',not_before=0,updated_at=? "
                    "WHERE dedup_key=? AND owner_user_id=? AND thread_id=? AND status IN ('failed','cancelled')",
                    (now, dedup, owner, thread),
                )
            row = conn.execute(
                "SELECT * FROM thread_metadata_jobs WHERE dedup_key=? AND owner_user_id=? AND thread_id=?",
                (dedup, owner, thread),
            ).fetchone()
        if row is None:
            raise ValueError("METADATA_JOB_CONFLICT")
        return self._job(row)

    @staticmethod
    def _job(row: Any) -> dict[str, Any]:
        return {
            **dict(row),
            "request": json.loads(row["request_json"]),
            "result": json.loads(row["result_json"]),
        }

    def job(self, owner: int, thread: str, identity: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM thread_metadata_jobs WHERE job_id=? AND owner_user_id=? AND thread_id=?",
                (identity, owner, thread),
            ).fetchone()
        return self._job(row) if row else None

    def pending(self, thread: str) -> bool:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM thread_metadata_jobs WHERE thread_id=? AND status IN ('queued','retry','running') LIMIT 1",
                (thread,),
            ).fetchone()
        return row is not None

    def claim(self) -> dict[str, Any] | None:
        now, token = time.time(), new_ulid()
        with self.db.transaction() as conn:
            candidates = conn.execute(
                "SELECT j.* FROM thread_metadata_jobs j WHERE "
                "((j.status IN ('queued','retry') AND j.not_before<=?) OR (j.status='running' AND j.lease_until<=?)) "
                "AND NOT EXISTS (SELECT 1 FROM thread_metadata_jobs busy WHERE busy.owner_user_id=j.owner_user_id AND busy.status='running' AND busy.lease_until>?) "
                "ORDER BY CASE WHEN j.status='running' THEN 0 ELSE 1 END,CASE WHEN j.kind='auto' THEN 1 ELSE 0 END,j.created_at,j.id LIMIT 16",
                (now, now, now),
            ).fetchall()
            for candidate in candidates:
                owner = candidate["owner_user_id"]
                if self.db.dialect == "postgresql":
                    conn.execute(
                        "SELECT id FROM users WHERE id=? FOR NO KEY UPDATE", (owner,)
                    ).fetchone()
                busy = conn.execute(
                    "SELECT 1 FROM thread_metadata_jobs WHERE owner_user_id=? AND status='running' AND lease_until>?",
                    (owner, now),
                ).fetchone()
                if busy:
                    continue
                changed = conn.execute(
                    "UPDATE thread_metadata_jobs SET status='running',attempts=attempts+1,lease_token=?,lease_until=?,updated_at=? "
                    "WHERE job_id=? AND ((status IN ('queued','retry') AND not_before<=?) OR (status='running' AND lease_until<=?))",
                    (token, now + 45, now, candidate["job_id"], now, now),
                ).rowcount
                if changed:
                    row = conn.execute(
                        "SELECT * FROM thread_metadata_jobs WHERE job_id=?", (candidate["job_id"],)
                    ).fetchone()
                    return self._job(row)
        return None

    def finish(
        self,
        job: dict[str, Any],
        status: str,
        result: dict[str, Any] | None = None,
        error: str = "",
        delay: float = 0,
    ) -> bool:
        with self.db.transaction() as conn:
            changed = conn.execute(
                "UPDATE thread_metadata_jobs SET status=?,result_json=?,error_code=?,not_before=?,lease_until=0,lease_token='',updated_at=? "
                "WHERE job_id=? AND lease_token=? AND status='running' AND lease_until>?",
                (
                    status,
                    encoded(result or {}),
                    error,
                    time.time() + delay,
                    time.time(),
                    job["job_id"],
                    job["lease_token"],
                    time.time(),
                ),
            ).rowcount
            if changed and error and status == "failed":
                conn.execute(
                    "UPDATE thread_metadata SET last_error=? WHERE thread_id=?",
                    (error, job["thread_id"]),
                )
            elif changed and status == "ready":
                conn.execute(
                    "UPDATE thread_metadata SET last_error='' WHERE thread_id=?",
                    (job["thread_id"],),
                )
        return bool(changed)

    def renew(self, job: dict[str, Any]) -> bool:
        with self.db.transaction() as conn:
            changed = conn.execute(
                "UPDATE thread_metadata_jobs SET lease_until=? WHERE job_id=? AND lease_token=? AND status='running' AND lease_until>?",
                (time.time() + 45, job["job_id"], job["lease_token"], time.time()),
            ).rowcount
        return bool(changed)

    def retry_partial(self, job: dict[str, Any], delay: float = 0) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE thread_metadata_jobs SET status='queued',attempts=0,lease_until=0,lease_token='',not_before=? WHERE job_id=? AND lease_token=? AND status='running' AND lease_until>?",
                (time.time() + delay, job["job_id"], job["lease_token"], time.time()),
            )

    def checkpoint(self, job: dict[str, Any], request: dict[str, Any]) -> bool:
        with self.db.transaction() as conn:
            changed = conn.execute(
                "UPDATE thread_metadata_jobs SET request_json=? WHERE job_id=? AND lease_token=? AND status='running' AND lease_until>?",
                (encoded(request), job["job_id"], job["lease_token"], time.time()),
            ).rowcount
        return bool(changed)

    def message_refs(self, thread: str, seqs: list[int]) -> list[dict[str, Any]]:
        if not seqs:
            return []
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT seq,message_id,role,message_json,created_at FROM thread_messages WHERE thread_id=? AND seq IN ({','.join('?' for _ in seqs)}) ORDER BY seq",
                [thread, *seqs],
            ).fetchall()
        return [dict(row) for row in rows]

    def commit(
        self,
        job: dict[str, Any],
        *,
        source_revision: int,
        manual_revision: int,
        config_revision: int,
        snapshot: dict[str, Any] | None = None,
        title: str | None = None,
        title_revision: int = 0,
        title_mode: str = "automatic",
        events: list[dict[str, Any]] | None = None,
        complete: bool = True,
    ) -> bool:
        """Source, manual, configuration and lease checks share the commit transaction."""
        thread = job["thread_id"]
        with self.db.transaction() as conn:
            if self.db.dialect == "postgresql":
                # Serialize configuration changes and source/manual writers too.
                # Source transactions lock metadata before updating the auto job.
                conn.execute(
                    "SELECT id FROM users WHERE id=? FOR NO KEY UPDATE", (job["owner_user_id"],)
                ).fetchone()
                conn.execute(
                    "SELECT a.agent_id FROM agents a JOIN threads t ON t.agent_id=a.agent_id "
                    "WHERE t.thread_id=? FOR SHARE OF a",
                    (thread,),
                ).fetchone()
                conn.execute(
                    "SELECT thread_id FROM threads WHERE thread_id=? FOR NO KEY UPDATE", (thread,)
                ).fetchone()
                conn.execute(
                    "SELECT thread_id FROM thread_metadata WHERE thread_id=? FOR UPDATE", (thread,)
                ).fetchone()
            valid = conn.execute(
                "SELECT 1 FROM thread_metadata_jobs j JOIN thread_metadata m ON m.thread_id=j.thread_id "
                "JOIN users u ON u.id=j.owner_user_id JOIN threads t ON t.thread_id=j.thread_id JOIN agents a ON a.agent_id=t.agent_id "
                "WHERE j.job_id=? AND j.lease_token=? AND j.status='running' AND t.user_id=j.owner_user_id "
                "AND t.agent_id=j.agent_id AND (a.user_id=j.owner_user_id OR a.is_shared=1) "
                "AND j.lease_until>? AND m.source_revision=? AND m.revision=? AND u.disabled=0",
                (job["job_id"], job["lease_token"], time.time(), source_revision, manual_revision),
            ).fetchone()
            settings = conn.execute(
                "SELECT value FROM settings WHERE key=?", (settings_key(job["owner_user_id"]),)
            ).fetchone()
            if (
                not valid
                or int((json.loads(settings["value"]) if settings else {}).get("revision", 0))
                != config_revision
            ):
                return False
            if title:
                sources = "('fallback','automatic')" if title_mode == "restore" else "('fallback')"
                conn.execute(
                    f"UPDATE threads SET title=?,title_source='automatic',title_revision=title_revision+1,title_updated_at=? "
                    f"WHERE thread_id=? AND title_revision=? AND title_source IN {sources}",
                    (title, time.time(), thread, title_revision),
                )
            if snapshot is not None:
                conn.execute(
                    "UPDATE thread_metadata SET snapshot_json=?,generated_source_revision=?,generated_at=?,dirty=?,last_error='',revision=revision+1 WHERE thread_id=?",
                    (encoded(snapshot), source_revision, time.time(), int(not complete), thread),
                )
            for event in events or []:
                record_semantic_event(
                    conn,
                    thread,
                    event["source_key"],
                    event["kind"],
                    event["payload"],
                    event["occurred_at"],
                )
        return True

    def title_action(
        self, thread: str, expected: int, action: str, title: str | None = None
    ) -> bool:
        with self.db.transaction() as conn:
            if action == "restore":
                changed = conn.execute(
                    "UPDATE threads SET title_source='fallback',title_revision=title_revision+1 WHERE thread_id=? AND title_revision=?",
                    (thread, expected),
                ).rowcount
            else:
                changed = conn.execute(
                    "UPDATE threads SET title=?,title_source='user',title_revision=title_revision+1,title_updated_at=? WHERE thread_id=? AND title_revision=?",
                    (title, time.time(), thread, expected),
                ).rowcount
        return bool(changed)

    def events(
        self,
        thread: str,
        start: float,
        end: float,
        *,
        after: tuple[float, str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM thread_semantic_events WHERE thread_id=? AND occurred_at>=? AND occurred_at<? "
                + ("AND (occurred_at>? OR (occurred_at=? AND event_id>?)) " if after else "")
                + "ORDER BY occurred_at,event_id LIMIT ?",
                [thread, start, end, *([after[0], after[0], after[1]] if after else []), limit],
            ).fetchall()
        return [
            {
                "event_id": r["event_id"],
                "kind": r["kind"],
                "occurred_at": r["occurred_at"],
                "recorded_at": r["recorded_at"],
                **json.loads(r["payload_json"]),
            }
            for r in rows
        ]

    def digest(
        self, identity: str, thread: str, *, by_cache: bool = False
    ) -> dict[str, Any] | None:
        column = "cache_key" if by_cache else "digest_id"
        with self.db.connect() as conn:
            row = conn.execute(
                f"SELECT payload_json FROM thread_digests WHERE {column}=? AND thread_id=?",
                (identity, thread),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def source_events(self, thread: str, after: int, limit: int = 9) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM thread_semantic_events WHERE thread_id=? AND source_key NOT LIKE 'semantic:%' "
                + "AND id>? ORDER BY id LIMIT ?",
                [thread, after, limit],
            ).fetchall()
        return [
            {
                "seq": row["id"],
                "event_id": row["event_id"],
                "kind": row["kind"],
                "occurred_at": row["occurred_at"],
                **json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    def event(self, thread: str, identity: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM thread_semantic_events WHERE thread_id=? AND event_id=?",
                (thread, identity),
            ).fetchone()
        return (
            {
                "event_id": row["event_id"],
                "occurred_at": row["occurred_at"],
                **json.loads(row["payload_json"]),
            }
            if row
            else None
        )

    def save_digest(
        self,
        thread: str,
        cache: str,
        revision: int,
        payload: dict[str, Any],
        *,
        job: dict[str, Any] | None = None,
        config_revision: int = 0,
    ) -> bool:
        with self.db.transaction() as conn:
            if job is not None:
                lease = conn.execute(
                    "SELECT 1 FROM thread_metadata_jobs j JOIN users u ON u.id=j.owner_user_id WHERE j.job_id=? AND j.lease_token=? AND j.status='running' AND j.lease_until>? AND u.disabled=0",
                    (job["job_id"], job["lease_token"], time.time()),
                ).fetchone()
                settings = conn.execute(
                    "SELECT value FROM settings WHERE key=?", (settings_key(job["owner_user_id"]),)
                ).fetchone()
                if (
                    not lease
                    or int((json.loads(settings["value"]) if settings else {}).get("revision", 0))
                    != config_revision
                ):
                    return False
            conn.execute(
                "INSERT INTO thread_digests(digest_id,thread_id,cache_key,source_revision,payload_json,created_at) VALUES (?,?,?,?,?,?) ON CONFLICT(cache_key) DO NOTHING",
                (payload["digest_id"], thread, cache, revision, encoded(payload), time.time()),
            )
        return True

    def messages(self, thread: str, after: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT seq,message_id,role,message_json,created_at FROM thread_messages WHERE thread_id=? AND seq>? ORDER BY seq LIMIT ?",
                (thread, after, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_briefs(self, owner: int, agent: str, threads: list[str]) -> dict[str, dict[str, Any]]:
        if not threads:
            return {}
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT m.*, (SELECT MAX(r.updated_at) FROM run_events r WHERE r.thread_id=t.thread_id AND r.owner_user_id=t.user_id "
                "AND r.agent_id=t.agent_id AND r.kind IN ('dispatch','job','tool','device') AND r.status IN ('running','started','accepted','waiting')) AS active_at "
                "FROM thread_metadata m JOIN threads t ON t.thread_id=m.thread_id WHERE t.user_id=? AND t.agent_id=? "
                f"AND t.thread_id IN ({','.join('?' for _ in threads)})",
                [owner, agent, *threads],
            ).fetchall()
        result = {}
        for row in rows:
            snapshot, manual = json.loads(row["snapshot_json"]), json.loads(row["manual_json"])
            brief = snapshot.get("brief") or {}
            version = max(snapshot.get("objective_version", 1), manual.get("objective_version", 1))
            work = (
                manual.get("work_state")
                if manual.get("objective_version", version) == version
                else None
            )
            work = work or (
                "in_progress" if manual.get("objective", brief.get("objective")) else "unknown"
            )
            active_at = row["active_at"]
            display = (
                ("running" if time.time() - active_at <= 45 else "unknown")
                if active_at is not None
                else work
            )
            result[str(row["thread_id"])] = {
                "one_liner": brief.get("one_liner", ""),
                "stage": brief.get("stage", ""),
                "recent_events": [item["text"] for item in brief.get("events", [])[-3:]],
                "work_state": work,
                "display_state": display,
                "freshness": "unavailable"
                if not snapshot
                else "stale"
                if row["dirty"]
                else "partial"
                if not snapshot.get("coverage", {}).get("complete")
                else "current",
                "generated_at": row["generated_at"],
            }
        return result
