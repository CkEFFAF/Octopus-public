-- Device policy is independent of navigation roots and working directories.
ALTER TABLE devices ADD COLUMN trust_mode TEXT NOT NULL DEFAULT 'restricted';
ALTER TABLE devices ADD COLUMN applied_trust_mode TEXT NOT NULL DEFAULT 'restricted';
ALTER TABLE devices ADD COLUMN policy_revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE devices ADD COLUMN applied_policy_revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE devices ADD COLUMN working_dir TEXT;
ALTER TABLE devices ADD COLUMN runtime_metadata TEXT NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS execution_contexts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    context_id TEXT NOT NULL UNIQUE,
    owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_id TEXT,
    thread_id TEXT,
    run_id TEXT,
    device_id TEXT REFERENCES devices(device_id) ON DELETE CASCADE,
    target_kind TEXT NOT NULL DEFAULT 'device',
    working_dir TEXT,
    policy_revision INTEGER NOT NULL,
    grant_version INTEGER NOT NULL,
    work_mode TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_execution_context_thread ON execution_contexts(owner_user_id, thread_id, created_at);
CREATE TABLE IF NOT EXISTS thread_execution_settings (
    thread_id TEXT PRIMARY KEY REFERENCES threads(thread_id) ON DELETE CASCADE,
    owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id TEXT REFERENCES devices(device_id) ON DELETE SET NULL,
    target_kind TEXT NOT NULL DEFAULT 'device',
    working_dir TEXT,
    work_mode TEXT NOT NULL DEFAULT 'agentic'
);
CREATE TABLE IF NOT EXISTS request_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL UNIQUE,
    owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_request_snapshots_thread ON request_snapshots(owner_user_id, thread_id, id);
CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_id TEXT REFERENCES agents(agent_id) ON DELETE CASCADE,
    thread_id TEXT REFERENCES threads(thread_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    context_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_run_events_thread ON run_events(owner_user_id, thread_id, id);
CREATE INDEX IF NOT EXISTS idx_run_events_jobs ON run_events(kind, updated_at, id);
UPDATE _schema_version SET version = 26;
