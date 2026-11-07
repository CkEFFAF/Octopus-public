-- 0045 restricted agent access keys + object grants (G5).
CREATE TABLE IF NOT EXISTS agent_access_keys (
  key_id TEXT PRIMARY KEY,
  owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  secret_hash TEXT NOT NULL UNIQUE,
  scopes_json TEXT NOT NULL,
  expert_ids_json TEXT NOT NULL,
  allow_existing_threads INTEGER NOT NULL DEFAULT 0,
  expires_at REAL NOT NULL,
  revoked_at REAL,
  last_used_at REAL,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_access_keys_owner
  ON agent_access_keys(owner_user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_access_object_grants (
  credential_id TEXT NOT NULL,
  object_kind TEXT NOT NULL,
  object_id TEXT NOT NULL,
  created_at REAL NOT NULL,
  PRIMARY KEY (credential_id, object_kind, object_id)
);
CREATE INDEX IF NOT EXISTS idx_agent_access_grants_object
  ON agent_access_object_grants(object_kind, object_id);

UPDATE _schema_version SET version=38;
