CREATE TABLE IF NOT EXISTS task_history_archives (
    owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_updated_at DOUBLE PRECISION NOT NULL,
    archived_at DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (owner_user_id, source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_task_history_archives_time
ON task_history_archives(owner_user_id, archived_at);
UPDATE _schema_version SET version = 41;
