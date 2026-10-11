CREATE TABLE IF NOT EXISTS account_access_keys (
    key_id TEXT PRIMARY KEY,
    owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    secret_hash TEXT NOT NULL UNIQUE,
    allow_browser INTEGER NOT NULL CHECK (allow_browser IN (0, 1)),
    allow_devices INTEGER NOT NULL CHECK (allow_devices IN (0, 1)),
    expires_at REAL NOT NULL,
    revoked_at REAL,
    last_used_at REAL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_account_access_keys_owner
    ON account_access_keys(owner_user_id, created_at DESC);
UPDATE _schema_version SET version = 23;
