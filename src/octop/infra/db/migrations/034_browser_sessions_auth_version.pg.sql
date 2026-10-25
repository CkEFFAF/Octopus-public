-- 0038 Batch2 F06: browser session revocation + users.auth_version
-- Rollback: DROP TABLE IF EXISTS browser_sessions; ALTER TABLE users DROP COLUMN IF EXISTS auth_version;
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_version INTEGER NOT NULL DEFAULT 1;
CREATE TABLE IF NOT EXISTS browser_sessions (
  sid TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at DOUBLE PRECISION NOT NULL,
  absolute_expires_at DOUBLE PRECISION NOT NULL,
  revoked_at DOUBLE PRECISION,
  auth_version_at_issue INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_browser_sessions_user ON browser_sessions(user_id);
UPDATE _schema_version SET version=34;
