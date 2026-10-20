CREATE TABLE IF NOT EXISTS cron_attempts (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 attempt_id TEXT NOT NULL UNIQUE,
 owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 agent_id TEXT NOT NULL,
 cron_id TEXT NOT NULL,
 source_thread_id TEXT,
 actual_thread_id TEXT,
 run_id TEXT UNIQUE,
 reason TEXT NOT NULL,
 status TEXT NOT NULL,
 revision INTEGER NOT NULL,
 created_at DOUBLE PRECISION NOT NULL,
 updated_at DOUBLE PRECISION NOT NULL,
 started_at DOUBLE PRECISION,
 finished_at DOUBLE PRECISION,
 public_error TEXT,
 result_excerpt TEXT
);
CREATE INDEX IF NOT EXISTS idx_cron_attempt_scope ON cron_attempts(owner_user_id,agent_id,cron_id,id);
UPDATE _schema_version SET version = 32;
