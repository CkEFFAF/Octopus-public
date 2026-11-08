"""Content-free, owner-scoped user activity and batched conversation signals."""

from __future__ import annotations

import json
import time
from typing import Any

from octop.infra.db.pool import DatabasePool


class ThreadActivityRepo:
    def __init__(self, db: DatabasePool) -> None:
        self.db = db

    def _json_text(self, column: str, *keys: str) -> str:
        if self.db.dialect == "postgresql":
            return f"(CAST({column} AS JSONB) #>> '{{{','.join(keys)}}}')"
        return f"json_extract({column},'$.{'.'.join(keys)}')"

    def record(
        self, owner: int, agent: str, thread: str, source_id: str, occurred_at: float | None = None
    ) -> bool:
        stamp = time.time() if occurred_at is None else occurred_at
        with self.db.transaction() as conn:
            changed = conn.execute(
                "INSERT INTO thread_user_activity(owner_user_id,agent_id,thread_id,source_id,occurred_at) "
                "SELECT user_id,agent_id,thread_id,?,? FROM threads WHERE user_id=? AND agent_id=? AND thread_id=? "
                "AND channel_type NOT IN ('cron_internal','work_item') "
                "ON CONFLICT(owner_user_id,thread_id,source_id) DO NOTHING",
                (source_id, stamp, owner, agent, thread),
            ).rowcount
            if changed:
                conn.execute(
                    "UPDATE thread_metadata_jobs SET not_before=CASE WHEN not_before<? THEN ? ELSE not_before END "
                    "WHERE owner_user_id=? AND thread_id=? AND kind='auto' AND status IN ('queued','retry')",
                    (stamp + 300, stamp + 300, owner, thread),
                )
        return bool(changed)

    def seed_legacy(self, since: float) -> None:
        source = (
            "COALESCE("
            + self._json_text("m.message_json", "data", "additional_kwargs", "lc_source")
            + ","
            + self._json_text("m.message_json", "additional_kwargs", "lc_source")
            + ",'')"
        )
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO thread_user_activity(owner_user_id,agent_id,thread_id,source_id,occurred_at,source_kind) "
                "SELECT t.user_id,t.agent_id,t.thread_id,CASE WHEN m.message_id IS NOT NULL AND m.message_id<>'' "
                "THEN 'human:' || m.message_id ELSE 'legacy:' || CAST(m.seq AS TEXT) END,m.created_at,'history' "
                "FROM thread_messages m JOIN threads t ON t.thread_id=m.thread_id "
                "WHERE m.role IN ('user','human') AND m.created_at>=? "
                "AND (m.message_id IS NULL OR m.message_id NOT LIKE 'cron:%') "
                f"AND {source} NOT IN ('summarization','pinned_skill') "
                "AND t.channel_type NOT IN ('cron_internal','work_item') "
                "AND NOT EXISTS (SELECT 1 FROM work_items w WHERE w.worker_thread_id=t.thread_id) "
                "ON CONFLICT(owner_user_id,thread_id,source_id) DO NOTHING",
                (since,),
            )
            conn.execute(
                "DELETE FROM thread_user_activity WHERE occurred_at<?", (time.time() - 90 * 86400,)
            )
            command = self._json_text("r.payload_json", "command_id")
            conn.execute(
                "INSERT INTO thread_user_activity(owner_user_id,agent_id,thread_id,source_id,occurred_at,source_kind) "
                f"SELECT r.owner_user_id,r.agent_id,r.thread_id,'human:steer:' || {command},r.created_at,'history' "
                "FROM run_events r JOIN threads t ON t.thread_id=r.thread_id AND t.user_id=r.owner_user_id AND t.agent_id=r.agent_id "
                "WHERE r.kind IN ('chat_input','chat_steer') AND r.status IN ('queued','dispatching','accepted','applied','cancelled') "
                f"AND r.created_at>=? AND {command} IS NOT NULL "
                "ON CONFLICT(owner_user_id,thread_id,source_id) DO NOTHING",
                (since,),
            )

    def seed_archive(self, samples: list[dict[str, Any]]) -> None:
        with self.db.transaction() as conn:
            for item in samples:
                conn.execute(
                    "INSERT INTO thread_user_activity(owner_user_id,agent_id,thread_id,source_id,occurred_at,source_kind) "
                    "SELECT t.user_id,t.agent_id,t.thread_id,?,?,'history' FROM threads t WHERE t.thread_id=? "
                    "AND t.channel_type NOT IN ('cron_internal','work_item') "
                    "AND NOT EXISTS (SELECT 1 FROM work_items w WHERE w.worker_thread_id=t.thread_id) "
                    "ON CONFLICT(owner_user_id,thread_id,source_id) DO NOTHING",
                    (item["source_id"], item["occurred_at"], item["thread_id"]),
                )

    def signals(self, owner: int, agent: str, now: float) -> dict[str, dict[str, Any]]:
        observation = self._json_text("j.payload_json", "observation", "status")
        with self.db.connect() as conn:
            activity = conn.execute(
                "SELECT thread_id,COUNT(*) AS interactions_7d,"
                "SUM(CASE WHEN occurred_at>=? THEN 1 ELSE 0 END) AS interactions_24h,MAX(occurred_at) AS last_user_at "
                "FROM thread_user_activity WHERE owner_user_id=? AND agent_id=? AND occurred_at>=? GROUP BY thread_id",
                (now - 86400, owner, agent, now - 7 * 86400),
            ).fetchall()
            work = conn.execute(
                "SELECT origin_thread_id AS thread_id,"
                "SUM(CASE WHEN created_at>=? THEN 1 ELSE 0 END) AS work_7d,"
                "SUM(CASE WHEN status IN ('queued','running') THEN 1 ELSE 0 END) AS background_count,"
                "SUM(CASE WHEN status IN ('waiting_input','waiting_review','blocked','unknown') THEN 1 ELSE 0 END) AS attention_count "
                "FROM work_items WHERE owner_user_id=? AND agent_id=? GROUP BY origin_thread_id",
                (now - 7 * 86400, owner, agent),
            ).fetchall()
            jobs = conn.execute(
                "SELECT j.thread_id,COUNT(*) AS jobs FROM run_events j JOIN threads t ON t.thread_id=j.thread_id "
                "AND t.user_id=j.owner_user_id AND t.agent_id=j.agent_id "
                "WHERE j.owner_user_id=? AND j.agent_id=? AND j.kind='job' "
                "AND j.status IN ('running','started','accepted','waiting') AND j.updated_at>=? "
                f"AND COALESCE({observation},'')<>'unavailable' GROUP BY j.thread_id",
                (owner, agent, now - 45),
            ).fetchall()
            refresh = conn.execute(
                "SELECT j.thread_id,j.not_before,j.result_json FROM thread_metadata_jobs j JOIN thread_metadata m ON m.thread_id=j.thread_id "
                "WHERE j.owner_user_id=? AND j.agent_id=? AND m.dirty=1 AND j.kind='auto' AND j.status IN ('queued','retry')",
                (owner, agent),
            ).fetchall()
            job_frequency = conn.execute(
                "SELECT thread_id,COUNT(*) AS work_7d FROM run_events WHERE owner_user_id=? AND agent_id=? "
                "AND kind='job' AND work_item_id IS NULL AND created_at>=? GROUP BY thread_id",
                (owner, agent, now - 7 * 86400),
            ).fetchall()
        values: dict[str, dict[str, Any]] = {}
        for row in [*activity, *work]:
            values.setdefault(str(row["thread_id"]), {}).update(dict(row))
        for row in jobs:
            value = values.setdefault(str(row["thread_id"]), {})
            value["background_count"] = int(value.get("background_count") or 0) + int(row["jobs"])
        for row in job_frequency:
            value = values.setdefault(str(row["thread_id"]), {})
            value["work_7d"] = int(value.get("work_7d") or 0) + int(row["work_7d"])
        for row in refresh:
            value = values.setdefault(str(row["thread_id"]), {})
            value["next_overview_at"] = float(row["not_before"])
            value["overview_reason"] = json.loads(row["result_json"] or "{}").get(
                "deferred_reason", ""
            )
        return values

    def profile(self, owner: int, now: float) -> list[float]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT occurred_at FROM thread_user_activity WHERE owner_user_id=? AND occurred_at>=? ORDER BY occurred_at",
                (owner, now - 28 * 86400),
            ).fetchall()
        return [float(row["occurred_at"]) for row in rows]
