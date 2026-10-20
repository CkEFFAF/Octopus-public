CREATE TABLE IF NOT EXISTS workbench_records (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 record_id TEXT NOT NULL UNIQUE,
 kind TEXT NOT NULL,
 owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 agent_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
 thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
 resource_id TEXT,
 revision INTEGER NOT NULL,
 payload_json TEXT NOT NULL,
 created_at DOUBLE PRECISION NOT NULL,
 updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workbench_scope ON workbench_records(owner_user_id,agent_id,thread_id,kind,id);
CREATE INDEX IF NOT EXISTS idx_workbench_resource ON workbench_records(owner_user_id,resource_id,kind,id);
UPDATE _schema_version SET version = 31;
