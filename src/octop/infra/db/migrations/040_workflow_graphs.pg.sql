CREATE TABLE IF NOT EXISTS workflow_graphs (
 owner_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 graph_id TEXT NOT NULL, name TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
 draft_json TEXT NOT NULL, published_revision INTEGER,
 next_due_at DOUBLE PRECISION, trigger_generation INTEGER NOT NULL DEFAULT 0,
 created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL, archived_at DOUBLE PRECISION,
 PRIMARY KEY(owner_user_id,graph_id)
);
CREATE INDEX IF NOT EXISTS workflow_graph_due ON workflow_graphs(next_due_at);
CREATE TABLE IF NOT EXISTS workflow_graph_versions (
 owner_user_id BIGINT NOT NULL, graph_id TEXT NOT NULL, revision INTEGER NOT NULL,
 definition_json TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL,
 PRIMARY KEY(owner_user_id,graph_id,revision),
 FOREIGN KEY(owner_user_id,graph_id) REFERENCES workflow_graphs(owner_user_id,graph_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS workflow_runs (
 id TEXT PRIMARY KEY, owner_user_id BIGINT NOT NULL,
 graph_id TEXT NOT NULL, version INTEGER NOT NULL,
 request_key TEXT NOT NULL, request_fingerprint TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'queued', initial_json TEXT NOT NULL,
 steps INTEGER NOT NULL DEFAULT 0, next_ordinal INTEGER NOT NULL DEFAULT 0,
 max_steps INTEGER NOT NULL, max_parallel INTEGER NOT NULL DEFAULT 4 CHECK(max_parallel BETWEEN 1 AND 4), deadline DOUBLE PRECISION NOT NULL,
 pause_requested INTEGER NOT NULL DEFAULT 0, cancel_requested INTEGER NOT NULL DEFAULT 0,
 error TEXT NOT NULL DEFAULT '', created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL,
 UNIQUE(owner_user_id,graph_id,request_key), UNIQUE(owner_user_id,id),
 FOREIGN KEY(owner_user_id,graph_id,version) REFERENCES workflow_graph_versions(owner_user_id,graph_id,revision) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS workflow_run_owner_time ON workflow_runs(owner_user_id,created_at,id);
CREATE INDEX IF NOT EXISTS workflow_run_status ON workflow_runs(status,updated_at);
CREATE TABLE IF NOT EXISTS workflow_activations (
 id TEXT PRIMARY KEY, owner_user_id BIGINT NOT NULL, run_id TEXT NOT NULL,
 node_id TEXT NOT NULL, kind TEXT NOT NULL, ordinal INTEGER NOT NULL,
 capacity_held INTEGER NOT NULL DEFAULT 0 CHECK(capacity_held IN (0,1)),
 parent_id TEXT NOT NULL DEFAULT '', incoming_edge TEXT NOT NULL DEFAULT '',
 group_id TEXT NOT NULL DEFAULT '', branch_id TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'ready', token_json TEXT NOT NULL,
 input_json TEXT NOT NULL DEFAULT '{}', output_json TEXT NOT NULL DEFAULT '{}',
 before_json TEXT NOT NULL DEFAULT '{}', after_json TEXT NOT NULL DEFAULT '{}',
 evidence_json TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '',
 worker_id TEXT NOT NULL DEFAULT '', lease_until DOUBLE PRECISION, next_at DOUBLE PRECISION,
 created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL,
 UNIQUE(run_id,ordinal),
 FOREIGN KEY(owner_user_id,run_id) REFERENCES workflow_runs(owner_user_id,id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS workflow_activation_ready ON workflow_activations(status,created_at);
CREATE INDEX IF NOT EXISTS workflow_activation_run ON workflow_activations(owner_user_id,run_id,ordinal);
CREATE INDEX IF NOT EXISTS workflow_activation_join ON workflow_activations(run_id,node_id,group_id,status);
CREATE TABLE IF NOT EXISTS workflow_admission (id INTEGER PRIMARY KEY CHECK(id=1), epoch BIGINT NOT NULL DEFAULT 0);
INSERT INTO workflow_admission(id) VALUES(1) ON CONFLICT(id) DO NOTHING;
UPDATE _schema_version SET version=40;
