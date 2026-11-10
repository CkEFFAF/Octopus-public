"""Owner-scoped definitions and durable activation claims. No runtime dispatch."""

from __future__ import annotations

import time
from typing import Any

from octop.infra.db.pool import DatabasePool


class WorkflowGraphRepo:
    def __init__(self, db: DatabasePool) -> None:
        self.db = db

    def get(self, owner: int, graph_id: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_graphs WHERE owner_user_id=? AND graph_id=?",
                (owner, graph_id),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_graphs(self, owner: int, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_graphs WHERE owner_user_id=? AND archived_at IS NULL "
                "ORDER BY updated_at DESC,graph_id LIMIT ? OFFSET ?",
                (owner, limit, offset),
            ).fetchall()
            count = conn.execute(
                "SELECT COUNT(*) FROM workflow_graphs WHERE owner_user_id=? AND archived_at IS NULL",
                (owner,),
            ).fetchone()[0]
        return [dict(row) for row in rows], int(count)

    def save(self, owner: int, graph_id: str, expected: int, name: str, payload: str) -> bool:
        now = time.time()
        with self.db.transaction() as conn:
            if expected == 0:
                conn.execute(
                    "INSERT INTO workflow_graphs(owner_user_id,graph_id,name,draft_json,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?) ON CONFLICT(owner_user_id,graph_id) DO NOTHING",
                    (owner, graph_id, name, payload, now, now),
                )
            row = conn.execute(
                "SELECT revision,draft_json,archived_at FROM workflow_graphs WHERE owner_user_id=? AND graph_id=?",
                (owner, graph_id),
            ).fetchone()
            if row is None or row["archived_at"] is not None:
                return False
            if int(row["revision"]) != expected:
                return int(row["revision"]) == expected + 1 and row["draft_json"] == payload
            return bool(
                conn.execute(
                    "UPDATE workflow_graphs SET revision=revision+1,name=?,draft_json=?,updated_at=? "
                    "WHERE owner_user_id=? AND graph_id=? AND revision=?",
                    (name, payload, now, owner, graph_id, expected),
                ).rowcount
            )

    def publish(self, owner: int, graph_id: str, expected: int, next_due: float | None) -> bool:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_graphs WHERE owner_user_id=? AND graph_id=? AND revision=? AND archived_at IS NULL",
                (owner, graph_id, expected),
            ).fetchone()
            if row is None:
                return False
            conn.execute(
                "INSERT INTO workflow_graph_versions(owner_user_id,graph_id,revision,definition_json,created_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(owner_user_id,graph_id,revision) DO NOTHING",
                (owner, graph_id, expected, row["draft_json"], time.time()),
            )
            return bool(
                conn.execute(
                    "UPDATE workflow_graphs SET published_revision=?,next_due_at=? WHERE owner_user_id=? AND graph_id=? AND revision=?",
                    (expected, next_due, owner, graph_id, expected),
                ).rowcount
            )

    def version(self, owner: int, graph_id: str, revision: int) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_graph_versions WHERE owner_user_id=? AND graph_id=? AND revision=?",
                (owner, graph_id, revision),
            ).fetchone()
        return dict(row) if row is not None else None

    def archive(self, owner: int, graph_id: str, expected: int) -> bool:
        with self.db.transaction() as conn:
            return bool(
                conn.execute(
                    "UPDATE workflow_graphs SET archived_at=?,next_due_at=NULL WHERE owner_user_id=? AND graph_id=? AND revision=?",
                    (time.time(), owner, graph_id, expected),
                ).rowcount
            )

    def run(self, owner: int, run_id: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_runs WHERE owner_user_id=? AND id=?", (owner, run_id)
            ).fetchone()
        return dict(row) if row is not None else None

    def list_runs(
        self, owner: int, graph_id: str, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_runs WHERE owner_user_id=? AND graph_id=? ORDER BY created_at DESC,id LIMIT ? OFFSET ?",
                (owner, graph_id, limit, offset),
            ).fetchall()
            count = conn.execute(
                "SELECT COUNT(*) FROM workflow_runs WHERE owner_user_id=? AND graph_id=?",
                (owner, graph_id),
            ).fetchone()[0]
        return [dict(row) for row in rows], int(count)

    def activations(self, owner: int, run_id: str) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM workflow_activations WHERE owner_user_id=? AND run_id=? ORDER BY ordinal",
                    (owner, run_id),
                )
            ]

    def activation_page(
        self, owner: int, run_id: str, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT id,node_id,kind,ordinal,parent_id,incoming_edge,group_id,branch_id,status,error,next_at,created_at,updated_at FROM workflow_activations WHERE owner_user_id=? AND run_id=? ORDER BY ordinal LIMIT ? OFFSET ?",
                (owner, run_id, limit, offset),
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) FROM workflow_activations WHERE owner_user_id=? AND run_id=?",
                (owner, run_id),
            ).fetchone()[0]
        return [dict(row) for row in rows], int(total)

    def latest_nodes(self, owner: int, run_id: str) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "WITH ranked AS (SELECT id,node_id,kind,ordinal,status,error,created_at,ROW_NUMBER() OVER(PARTITION BY node_id ORDER BY ordinal DESC) AS rank FROM workflow_activations WHERE owner_user_id=? AND run_id=?) SELECT id,node_id,kind,ordinal,status,error,created_at FROM ranked WHERE rank=1 ORDER BY ordinal",
                (owner, run_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def enforce_budgets(self, now: float) -> None:
        with self.db.transaction() as conn:
            self._admission(conn)
            rows = conn.execute(
                "SELECT owner_user_id,id FROM workflow_runs WHERE status IN ('queued','running','waiting') AND (deadline<=? OR steps>=max_steps)",
                (now,),
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE workflow_runs SET pause_requested=1,error='workflow budget exhausted' WHERE owner_user_id=? AND id=?",
                    (row["owner_user_id"], row["id"]),
                )
                self._settle(conn, row["owner_user_id"], row["id"], now)

    @staticmethod
    def _admission(conn: Any) -> None:
        conn.execute("UPDATE workflow_admission SET epoch=epoch+1 WHERE id=1")

    def create_run(
        self,
        *,
        owner: int,
        graph_id: str,
        version: int,
        run_id: str,
        key: str,
        fingerprint: str,
        initial: str,
        max_steps: int,
        deadline: float,
        entry: dict[str, Any],
        expected_published: int | None = None,
        max_parallel: int = 4,
        schedule_due: float | None = None,
        next_due: float | None = None,
        skip_if_active: bool = False,
    ) -> tuple[str, bool]:
        now = time.time()
        with self.db.transaction() as conn:
            self._admission(conn)
            prior = conn.execute(
                "SELECT id,request_fingerprint FROM workflow_runs WHERE owner_user_id=? AND graph_id=? AND request_key=?",
                (owner, graph_id, key),
            ).fetchone()
            if prior:
                if prior["request_fingerprint"] != fingerprint:
                    raise ValueError("run idempotency key reused with different inputs")
                return str(prior["id"]), False
            graph = conn.execute(
                "SELECT published_revision,archived_at,next_due_at FROM workflow_graphs WHERE owner_user_id=? AND graph_id=?",
                (owner, graph_id),
            ).fetchone()
            if (
                graph is None
                or graph["archived_at"] is not None
                or (
                    expected_published is not None
                    and graph["published_revision"] != expected_published
                )
            ):
                raise ValueError("published graph changed or became unavailable")
            if schedule_due is not None and graph["next_due_at"] != schedule_due:
                raise ValueError("schedule occurrence was already claimed")
            skip = (
                skip_if_active
                and conn.execute(
                    "SELECT id FROM workflow_runs WHERE owner_user_id=? AND graph_id=? AND status NOT IN ('succeeded','failed','cancelled','skipped') LIMIT 1",
                    (owner, graph_id),
                ).fetchone()
                is not None
            )
            queued = conn.execute(
                "SELECT owner_user_id,COUNT(*) AS n FROM workflow_runs WHERE status NOT IN ('succeeded','failed','cancelled','skipped') GROUP BY owner_user_id"
            ).fetchall()
            if not skip and (
                sum(int(row["n"]) for row in queued) >= 128
                or any(row["owner_user_id"] == owner and int(row["n"]) >= 32 for row in queued)
            ):
                raise ValueError("workflow queue is full")
            conn.execute(
                "INSERT INTO workflow_runs(id,owner_user_id,graph_id,version,request_key,request_fingerprint,initial_json,max_steps,max_parallel,deadline,status,error,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    owner,
                    graph_id,
                    version,
                    key,
                    fingerprint,
                    initial,
                    max_steps,
                    max_parallel,
                    deadline,
                    "skipped" if skip else "queued",
                    "previous scheduled instance is active" if skip else "",
                    now,
                    now,
                ),
            )
            if not skip:
                self._insert_activation(conn, owner, run_id, entry, now)
            if schedule_due is not None:
                conn.execute(
                    "UPDATE workflow_graphs SET next_due_at=? WHERE owner_user_id=? AND graph_id=? AND next_due_at=?",
                    (next_due, owner, graph_id, schedule_due),
                )
            return run_id, True

    @staticmethod
    def _insert_activation(
        conn: Any, owner: int, run_id: str, item: dict[str, Any], now: float
    ) -> None:
        row = conn.execute(
            "SELECT next_ordinal FROM workflow_runs WHERE owner_user_id=? AND id=?", (owner, run_id)
        ).fetchone()
        ordinal = int(row["next_ordinal"]) + 1
        conn.execute(
            "UPDATE workflow_runs SET next_ordinal=? WHERE owner_user_id=? AND id=?",
            (ordinal, owner, run_id),
        )
        conn.execute(
            "INSERT INTO workflow_activations(id,owner_user_id,run_id,node_id,kind,ordinal,parent_id,incoming_edge,group_id,branch_id,token_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                item["id"],
                owner,
                run_id,
                item["node_id"],
                item["kind"],
                ordinal,
                item.get("parent_id", ""),
                item.get("incoming_edge", ""),
                item.get("group_id", ""),
                item.get("branch_id", ""),
                item["token_json"],
                now,
                now,
            ),
        )

    def activation(self, owner: int, activation_id: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_activations WHERE owner_user_id=? AND id=?",
                (owner, activation_id),
            ).fetchone()
        return dict(row) if row is not None else None

    def ready(self, limit: int = 64, exclude: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        excluded = (
            "" if not exclude else " AND a.id NOT IN (" + ",".join("?" for _ in exclude) + ")"
        )
        with self.db.connect() as conn:
            rows = conn.execute(
                "WITH ready AS (SELECT a.*,ROW_NUMBER() OVER(PARTITION BY a.owner_user_id ORDER BY a.created_at,a.ordinal) AS owner_rank "
                "FROM workflow_activations a JOIN workflow_runs r ON r.id=a.run_id AND r.owner_user_id=a.owner_user_id "
                "WHERE a.status='ready' AND r.status IN ('queued','running','waiting') AND r.pause_requested=0 AND r.cancel_requested=0"
                + excluded
                + ") "
                "SELECT * FROM ready ORDER BY owner_rank,created_at LIMIT ?",
                (*exclude, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def claim(self, owner: int, activation_id: str, worker: str, now: float) -> bool:
        with self.db.transaction() as conn:
            self._admission(conn)
            row = conn.execute(
                "SELECT a.*,r.steps,r.max_steps,r.max_parallel,r.deadline,r.pause_requested,r.cancel_requested,r.status AS run_status "
                "FROM workflow_activations a JOIN workflow_runs r ON r.id=a.run_id AND r.owner_user_id=a.owner_user_id "
                "WHERE a.owner_user_id=? AND a.id=?",
                (owner, activation_id),
            ).fetchone()
            if (
                row is None
                or row["status"] != "ready"
                or row["pause_requested"]
                or row["cancel_requested"]
                or row["run_status"] not in {"queued", "running", "waiting"}
            ):
                return False
            if row["steps"] >= row["max_steps"] or row["deadline"] <= now:
                conn.execute(
                    "UPDATE workflow_runs SET status='paused',pause_requested=1,error='workflow budget exhausted',updated_at=? WHERE owner_user_id=? AND id=?",
                    (now, owner, row["run_id"]),
                )
                self._settle(conn, owner, row["run_id"], now)
                return False
            if row["kind"] in {"agent", "script"}:
                active = conn.execute(
                    "SELECT COUNT(*) FROM workflow_activations WHERE capacity_held=1"
                ).fetchone()[0]
                active_run = conn.execute(
                    "SELECT COUNT(*) FROM workflow_activations WHERE run_id=? AND capacity_held=1",
                    (row["run_id"],),
                ).fetchone()[0]
                if int(active) >= 4 or int(active_run) >= row["max_parallel"]:
                    return False
            changed = conn.execute(
                "UPDATE workflow_activations SET status='running',capacity_held=CASE WHEN kind IN ('agent','script') THEN 1 ELSE 0 END,worker_id=?,lease_until=?,updated_at=? WHERE owner_user_id=? AND id=? AND status='ready'",
                (worker, now + 120, now, owner, activation_id),
            ).rowcount
            if changed:
                conn.execute(
                    "UPDATE workflow_runs SET status='running',steps=steps+1,updated_at=? WHERE owner_user_id=? AND id=?",
                    (now, owner, row["run_id"]),
                )
            return bool(changed)

    def renew(self, owner: int, activation_id: str, worker: str, now: float) -> bool:
        with self.db.transaction() as conn:
            return bool(
                conn.execute(
                    "UPDATE workflow_activations SET lease_until=?,updated_at=? WHERE owner_user_id=? AND id=? AND worker_id=? AND status='running' AND lease_until>?",
                    (now + 120, now, owner, activation_id, worker, now),
                ).rowcount
            )

    def owns_lease(self, owner: int, activation_id: str, worker: str, now: float) -> bool:
        with self.db.connect() as conn:
            return (
                conn.execute(
                    "SELECT id FROM workflow_activations WHERE owner_user_id=? AND id=? AND worker_id=? "
                    "AND status='running' AND lease_until>?",
                    (owner, activation_id, worker, now),
                ).fetchone()
                is not None
            )

    def update_activation(
        self,
        owner: int,
        activation_id: str,
        expected: str,
        values: dict[str, Any],
        *,
        worker: str | None = None,
    ) -> bool:
        allowed = {
            "status",
            "input_json",
            "output_json",
            "before_json",
            "after_json",
            "evidence_json",
            "error",
            "next_at",
            "token_json",
            "lease_until",
        }
        if not values or not set(values) <= allowed:
            raise ValueError("invalid activation update fields")
        assignments = ",".join(f"{key}=?" for key in values)
        args = [*values.values(), time.time(), owner, activation_id, expected]
        where = ""
        if worker is not None:
            where = " AND worker_id=? AND lease_until>?"
            args.extend([worker, time.time()])
        with self.db.transaction() as conn:
            changed = bool(
                conn.execute(
                    f"UPDATE workflow_activations SET {assignments},updated_at=? WHERE owner_user_id=? AND id=? AND status=?{where}",
                    args,
                ).rowcount
            )
            if changed and "status" in values:
                row = conn.execute(
                    "SELECT run_id FROM workflow_activations WHERE owner_user_id=? AND id=?",
                    (owner, activation_id),
                ).fetchone()
                self._settle(conn, owner, row["run_id"], time.time())
            return changed

    def waiting(self, limit: int = 128) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_activations WHERE (status IN ('waiting_job','waiting_event','waiting_time','waiting_join') OR (kind='script' AND capacity_held=1 AND status IN ('unknown','superseded'))) "
                "AND (next_at IS NULL OR next_at<=?) ORDER BY updated_at,id LIMIT ?",
                (time.time(), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def expire_leases(self, now: float) -> int:
        with self.db.transaction() as conn:
            self._admission(conn)
            rows = conn.execute(
                "SELECT owner_user_id,id,run_id FROM workflow_activations WHERE status='running' AND lease_until<=?",
                (now,),
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE workflow_activations SET status='unknown',error='worker lease expired; outcome requires reconciliation',updated_at=? WHERE id=? AND status='running' AND lease_until<=?",
                    (now, row["id"], now),
                )
                conn.execute(
                    "UPDATE workflow_runs SET status='unknown',pause_requested=1,error='an activation outcome is unknown',updated_at=? WHERE owner_user_id=? AND id=? AND cancel_requested=0",
                    (now, row["owner_user_id"], row["run_id"]),
                )
            return len(rows)

    def finish(
        self,
        owner: int,
        activation_id: str,
        expected: str,
        *,
        output: str,
        after: str,
        children: list[dict[str, Any]],
        worker: str | None = None,
    ) -> bool:
        now = time.time()
        with self.db.transaction() as conn:
            self._admission(conn)
            row = conn.execute(
                "SELECT * FROM workflow_activations WHERE owner_user_id=? AND id=?",
                (owner, activation_id),
            ).fetchone()
            if row is None or row["status"] != expected:
                return False
            if worker is not None and (
                row["worker_id"] != worker or not row["lease_until"] or row["lease_until"] <= now
            ):
                return False
            conn.execute(
                "UPDATE workflow_activations SET status='completed',capacity_held=0,output_json=?,after_json=?,lease_until=NULL,updated_at=? WHERE owner_user_id=? AND id=?",
                (output, after, now, owner, activation_id),
            )
            run = conn.execute(
                "SELECT * FROM workflow_runs WHERE owner_user_id=? AND id=?", (owner, row["run_id"])
            ).fetchone()
            if expected == "unknown" and not run["cancel_requested"]:
                conn.execute(
                    "UPDATE workflow_runs SET status='paused',pause_requested=1 WHERE owner_user_id=? AND id=?",
                    (owner, row["run_id"]),
                )
            if (
                not run["cancel_requested"]
                and run["status"]
                not in {
                    "failed",
                    "cancelled",
                }
                and (run["status"] != "unknown" or expected == "unknown")
            ):
                for child in children:
                    self._insert_activation(conn, owner, row["run_id"], child, now)
            self._settle(conn, owner, row["run_id"], now)
            return True

    def fail(
        self,
        owner: int,
        activation_id: str,
        expected: str,
        error: str,
        *,
        unknown: bool = False,
        worker: str | None = None,
        children: list[dict[str, Any]] | None = None,
    ) -> bool:
        now = time.time()
        with self.db.transaction() as conn:
            self._admission(conn)
            row = conn.execute(
                "SELECT * FROM workflow_activations WHERE owner_user_id=? AND id=?",
                (owner, activation_id),
            ).fetchone()
            if (
                row is None
                or row["status"] != expected
                or (
                    worker is not None
                    and (
                        row["worker_id"] != worker
                        or not row["lease_until"]
                        or row["lease_until"] <= now
                    )
                )
            ):
                return False
            conn.execute(
                "UPDATE workflow_activations SET status=?,error=?,lease_until=NULL,updated_at=? WHERE owner_user_id=? AND id=?",
                ("unknown" if unknown else "failed", error, now, owner, activation_id),
            )
            if not unknown:
                conn.execute(
                    "UPDATE workflow_activations SET capacity_held=0 WHERE owner_user_id=? AND id=?",
                    (owner, activation_id),
                )
            run = conn.execute(
                "SELECT * FROM workflow_runs WHERE owner_user_id=? AND id=?", (owner, row["run_id"])
            ).fetchone()
            if children and not unknown and not run["cancel_requested"]:
                for child in children:
                    self._insert_activation(conn, owner, row["run_id"], child, now)
            else:
                conn.execute(
                    "UPDATE workflow_runs SET status=?,pause_requested=?,error=?,updated_at=? WHERE owner_user_id=? AND id=?",
                    (
                        "unknown" if unknown else "failed",
                        int(unknown),
                        error,
                        now,
                        owner,
                        row["run_id"],
                    ),
                )
            self._settle(conn, owner, row["run_id"], now)
            return True

    def release_capacity(self, owner: int, activation_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE workflow_activations SET capacity_held=0 WHERE owner_user_id=? AND id=?",
                (owner, activation_id),
            )

    def uncertain_models(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT owner_user_id,id,worker_id FROM workflow_activations WHERE kind='agent' AND capacity_held=1 AND status IN ('unknown','superseded') LIMIT 128"
                )
            ]

    @staticmethod
    def _settle(conn: Any, owner: int, run_id: str, now: float) -> None:
        run = conn.execute(
            "SELECT * FROM workflow_runs WHERE owner_user_id=? AND id=?", (owner, run_id)
        ).fetchone()
        counts = {
            str(row["status"]): int(row["n"])
            for row in conn.execute(
                "SELECT status,COUNT(*) AS n FROM workflow_activations WHERE owner_user_id=? AND run_id=? GROUP BY status",
                (owner, run_id),
            )
        }
        active = counts.get("running", 0) + counts.get("waiting_job", 0)
        waiting = sum(
            counts.get(state, 0)
            for state in ("waiting_job", "waiting_event", "waiting_time", "waiting_join")
        )
        if run["cancel_requested"]:
            status = "cancelling" if active or counts.get("unknown", 0) else "cancelled"
        elif counts.get("unknown", 0):
            status = "unknown"
        elif run["status"] == "failed":
            return
        elif run["pause_requested"]:
            status = "pausing" if active else "paused"
        elif counts.get("ready", 0) or active:
            status = "running"
        elif waiting:
            status = "waiting"
        else:
            status = "succeeded"
        conn.execute(
            "UPDATE workflow_runs SET status=?,updated_at=? WHERE owner_user_id=? AND id=?",
            (status, now, owner, run_id),
        )

    def control(
        self,
        owner: int,
        run_id: str,
        action: str,
        *,
        max_steps: int | None = None,
        deadline: float | None = None,
    ) -> bool:
        now = time.time()
        with self.db.transaction() as conn:
            self._admission(conn)
            run = conn.execute(
                "SELECT * FROM workflow_runs WHERE owner_user_id=? AND id=?", (owner, run_id)
            ).fetchone()
            if run is None or run["status"] in {"succeeded", "cancelled", "skipped"}:
                return False
            if action == "pause":
                conn.execute(
                    "UPDATE workflow_runs SET pause_requested=1 WHERE owner_user_id=? AND id=?",
                    (owner, run_id),
                )
            elif action == "cancel":
                conn.execute(
                    "UPDATE workflow_runs SET cancel_requested=1 WHERE owner_user_id=? AND id=?",
                    (owner, run_id),
                )
                conn.execute(
                    "UPDATE workflow_activations SET status='cancelled',error='cancelled before dispatch',updated_at=? "
                    "WHERE owner_user_id=? AND run_id=? AND status IN ('ready','waiting_event','waiting_time','waiting_join')",
                    (now, owner, run_id),
                )
            elif action == "resume":
                unknown = conn.execute(
                    "SELECT id FROM workflow_activations WHERE owner_user_id=? AND run_id=? AND status='unknown' LIMIT 1",
                    (owner, run_id),
                ).fetchone()
                if unknown or run["cancel_requested"] or run["status"] == "failed":
                    return False
                selected_steps = max_steps if max_steps is not None else int(run["max_steps"])
                selected_deadline = deadline if deadline is not None else float(run["deadline"])
                if selected_steps <= run["steps"] or selected_deadline <= now:
                    return False
                conn.execute(
                    "UPDATE workflow_runs SET pause_requested=0,error='',max_steps=?,deadline=? WHERE owner_user_id=? AND id=?",
                    (selected_steps, selected_deadline, owner, run_id),
                )
            else:
                raise ValueError("unsupported run control")
            self._settle(conn, owner, run_id, now)
            return True

    def retry(self, owner: int, activation_id: str, replacement: dict[str, Any]) -> bool:
        now = time.time()
        with self.db.transaction() as conn:
            self._admission(conn)
            row = conn.execute(
                "SELECT * FROM workflow_activations WHERE owner_user_id=? AND id=?",
                (owner, activation_id),
            ).fetchone()
            if row is None or row["status"] not in {"unknown", "failed"}:
                return False
            run = conn.execute(
                "SELECT * FROM workflow_runs WHERE owner_user_id=? AND id=?", (owner, row["run_id"])
            ).fetchone()
            if (
                run["cancel_requested"]
                or run["steps"] >= run["max_steps"]
                or run["deadline"] <= now
            ):
                return False
            conn.execute(
                "UPDATE workflow_activations SET status='superseded',updated_at=? WHERE owner_user_id=? AND id=?",
                (now, owner, activation_id),
            )
            self._insert_activation(conn, owner, row["run_id"], replacement, now)
            conn.execute(
                "UPDATE workflow_runs SET status='queued',pause_requested=0,error='',updated_at=? WHERE owner_user_id=? AND id=?",
                (now, owner, row["run_id"]),
            )
            self._settle(conn, owner, row["run_id"], now)
            return True

    def record_evidence(self, owner: int, activation_id: str, worker: str, evidence: str) -> bool:
        # A late accepted receipt remains useful evidence even after a lost
        # lease. It never changes status or authorizes successor dispatch.
        with self.db.transaction() as conn:
            return bool(
                conn.execute(
                    "UPDATE workflow_activations SET evidence_json=?,updated_at=? WHERE owner_user_id=? AND id=? AND worker_id=?",
                    (evidence, time.time(), owner, activation_id, worker),
                ).rowcount
            )

    def arrive_join(self, owner: int, activation_id: str, worker: str) -> list[dict[str, Any]]:
        now = time.time()
        with self.db.transaction() as conn:
            self._admission(conn)
            row = conn.execute(
                "SELECT * FROM workflow_activations WHERE owner_user_id=? AND id=? AND status='running' AND worker_id=? AND lease_until>?",
                (owner, activation_id, worker, now),
            ).fetchone()
            if row is None:
                return []
            conn.execute(
                "UPDATE workflow_activations SET status='waiting_join',lease_until=NULL,updated_at=? WHERE owner_user_id=? AND id=?",
                (now, owner, activation_id),
            )
            return [
                dict(item)
                for item in conn.execute(
                    "SELECT * FROM workflow_activations WHERE owner_user_id=? AND run_id=? AND node_id=? AND group_id=? AND status='waiting_join' ORDER BY ordinal",
                    (owner, row["run_id"], row["node_id"], row["group_id"]),
                )
            ]

    def join_arrivals(
        self, owner: int, run_id: str, node_id: str, group_id: str
    ) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM workflow_activations WHERE owner_user_id=? AND run_id=? AND node_id=? AND group_id=? AND status='waiting_join' ORDER BY ordinal",
                    (owner, run_id, node_id, group_id),
                )
            ]

    def finish_join(
        self,
        owner: int,
        activation_ids: list[str],
        *,
        output: str,
        after: str,
        children: list[dict[str, Any]],
    ) -> bool:
        if not activation_ids:
            return False
        now = time.time()
        with self.db.transaction() as conn:
            self._admission(conn)
            marks = ",".join("?" for _ in activation_ids)
            rows = conn.execute(
                f"SELECT * FROM workflow_activations WHERE owner_user_id=? AND id IN ({marks}) AND status='waiting_join' ORDER BY ordinal",
                (owner, *activation_ids),
            ).fetchall()
            if (
                len(rows) != len(activation_ids)
                or len({(row["run_id"], row["node_id"], row["group_id"]) for row in rows}) != 1
            ):
                return False
            run_id = rows[0]["run_id"]
            conn.execute(
                f"UPDATE workflow_activations SET status='completed',output_json=?,after_json=?,updated_at=? WHERE owner_user_id=? AND id IN ({marks})",
                (output, after, now, owner, *activation_ids),
            )
            run = conn.execute(
                "SELECT * FROM workflow_runs WHERE owner_user_id=? AND id=?", (owner, run_id)
            ).fetchone()
            if not run["cancel_requested"] and run["status"] not in {
                "failed",
                "unknown",
                "cancelled",
            }:
                for child in children:
                    self._insert_activation(conn, owner, run_id, child, now)
            self._settle(conn, owner, run_id, now)
            return True

    def fail_join(
        self, owner: int, activation_ids: list[str], error: str, children: list[dict[str, Any]]
    ) -> bool:
        if not activation_ids:
            return False
        now = time.time()
        with self.db.transaction() as conn:
            self._admission(conn)
            marks = ",".join("?" for _ in activation_ids)
            rows = conn.execute(
                f"SELECT * FROM workflow_activations WHERE owner_user_id=? AND id IN ({marks}) AND status='waiting_join'",
                (owner, *activation_ids),
            ).fetchall()
            if (
                len(rows) != len(activation_ids)
                or len({(row["run_id"], row["node_id"], row["group_id"]) for row in rows}) != 1
            ):
                return False
            run_id = rows[0]["run_id"]
            conn.execute(
                f"UPDATE workflow_activations SET status='failed',error=?,updated_at=? WHERE owner_user_id=? AND id IN ({marks})",
                (error, now, owner, *activation_ids),
            )
            run = conn.execute(
                "SELECT * FROM workflow_runs WHERE owner_user_id=? AND id=?", (owner, run_id)
            ).fetchone()
            if (
                children
                and not run["cancel_requested"]
                and run["status"] not in {"failed", "unknown", "cancelled"}
            ):
                for child in children:
                    self._insert_activation(conn, owner, run_id, child, now)
            elif not run["cancel_requested"]:
                conn.execute(
                    "UPDATE workflow_runs SET status='failed',error=?,updated_at=? WHERE owner_user_id=? AND id=?",
                    (error, now, owner, run_id),
                )
            self._settle(conn, owner, run_id, now)
            return True

    def due_schedules(self, now: float, limit: int = 32) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT g.*,v.definition_json FROM workflow_graphs g JOIN workflow_graph_versions v ON v.owner_user_id=g.owner_user_id AND v.graph_id=g.graph_id AND v.revision=g.published_revision "
                    "WHERE g.archived_at IS NULL AND g.next_due_at IS NOT NULL AND g.next_due_at<=? ORDER BY g.next_due_at LIMIT ?",
                    (now, limit),
                )
            ]

    def advance_schedule(
        self, owner: int, graph_id: str, due: float, following: float | None
    ) -> bool:
        with self.db.transaction() as conn:
            return bool(
                conn.execute(
                    "UPDATE workflow_graphs SET next_due_at=? WHERE owner_user_id=? AND graph_id=? AND next_due_at=? AND archived_at IS NULL",
                    (following, owner, graph_id, due),
                ).rowcount
            )

    def blocked_schedule(
        self,
        owner: int,
        graph_id: str,
        version: int,
        due: float,
        following: float | None,
        identity: str,
        error: str,
    ) -> None:
        now = time.time()
        with self.db.transaction() as conn:
            self._admission(conn)
            changed = conn.execute(
                "UPDATE workflow_graphs SET next_due_at=? WHERE owner_user_id=? AND graph_id=? AND next_due_at=? AND archived_at IS NULL",
                (following, owner, graph_id, due),
            ).rowcount
            if changed:
                conn.execute(
                    "INSERT INTO workflow_runs(id,owner_user_id,graph_id,version,request_key,request_fingerprint,status,initial_json,max_steps,deadline,error,created_at,updated_at) VALUES(?,?,?,?,?,?,'failed','{}',1,?,?,?,?) ON CONFLICT(owner_user_id,graph_id,request_key) DO NOTHING",
                    (
                        identity,
                        owner,
                        graph_id,
                        version,
                        "schedule:" + str(due),
                        "admission-blocked",
                        now,
                        error,
                        now,
                        now,
                    ),
                )

    def rotate_capability(self, owner: int, graph_id: str, generation: int) -> bool:
        with self.db.transaction() as conn:
            return bool(
                conn.execute(
                    "UPDATE workflow_graphs SET trigger_generation=trigger_generation+1 WHERE owner_user_id=? AND graph_id=? AND trigger_generation=? AND archived_at IS NULL",
                    (owner, graph_id, generation),
                ).rowcount
            )

    def run_by_key(self, owner: int, graph_id: str, key: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_runs WHERE owner_user_id=? AND graph_id=? AND request_key=?",
                (owner, graph_id, key),
            ).fetchone()
        return dict(row) if row is not None else None
