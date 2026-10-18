CREATE TABLE IF NOT EXISTS thread_shares (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 share_id TEXT NOT NULL UNIQUE,
 owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 source_agent_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
 source_thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
 token_hash TEXT NOT NULL UNIQUE,
 encrypted_token TEXT,
 snapshot_json TEXT NOT NULL,
 snapshot_version INTEGER NOT NULL DEFAULT 1,
 message_count INTEGER NOT NULL,
 created_at DOUBLE PRECISION NOT NULL,
 expires_at DOUBLE PRECISION,
 revoked_at DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_thread_shares_owner ON thread_shares(owner_user_id,id);
CREATE INDEX IF NOT EXISTS idx_thread_shares_thread ON thread_shares(owner_user_id,source_thread_id,id);
UPDATE _schema_version SET version = 30;
