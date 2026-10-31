ALTER TABLE cron_attempts ADD COLUMN execution_thread_id TEXT;
ALTER TABLE cron_attempts ADD COLUMN checkpoint_cleanup TEXT;
CREATE TABLE IF NOT EXISTS cron_report_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  attempt_id TEXT NOT NULL UNIQUE REFERENCES cron_attempts(attempt_id) ON DELETE CASCADE,
  owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  agent_id TEXT NOT NULL,
  cron_id TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  output TEXT NOT NULL,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cron_reports_owner_job ON cron_report_results(owner_user_id, agent_id, cron_id, id);
UPDATE _schema_version SET version=35;
