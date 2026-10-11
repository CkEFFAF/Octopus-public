CREATE TABLE IF NOT EXISTS task_boards (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL DEFAULT '{"tasks":[]}'
);
UPDATE _schema_version SET version = 21;
