"""SQL persistence and optimistic concurrency for user task ledgers."""

from __future__ import annotations

from octop.infra.db.pool import DatabasePool


class TaskBoardRepo:
    def __init__(self, db: DatabasePool) -> None:
        self._db = db

    def get(self, user_id: int) -> tuple[int, str]:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT revision, payload FROM task_boards WHERE user_id = ?", (user_id,)
            ).fetchone()
        return (int(row["revision"]), str(row["payload"])) if row else (0, '{"tasks":[]}')

    def save(self, user_id: int, revision: int, payload: str) -> bool:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO task_boards(user_id) VALUES(?) ON CONFLICT(user_id) DO NOTHING",
                (user_id,),
            )
            result = conn.execute(
                "UPDATE task_boards SET revision = revision + 1, payload = ?"
                " WHERE user_id = ? AND revision = ?",
                (payload, user_id, revision),
            )
            return bool(result.rowcount == 1)

    def user_ids(self) -> list[int]:
        with self._db.connect() as conn:
            return [int(row["user_id"]) for row in conn.execute("SELECT user_id FROM task_boards")]
