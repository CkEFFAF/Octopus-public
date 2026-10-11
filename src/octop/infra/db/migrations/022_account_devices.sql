-- Native devices bound to an existing control-center account.
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL UNIQUE,
    owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    platform TEXT NOT NULL,
    capabilities TEXT NOT NULL DEFAULT '[]',
    permissions TEXT NOT NULL DEFAULT '[]',
    roots TEXT NOT NULL DEFAULT '[]',
    token_hash TEXT NOT NULL UNIQUE,
    grant_version INTEGER NOT NULL DEFAULT 1 CHECK (grant_version >= 1),
    last_seen_at REAL,
    revoked_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE (device_id, owner_user_id)
);
CREATE INDEX IF NOT EXISTS idx_devices_owner ON devices(owner_user_id, id);

CREATE TABLE IF NOT EXISTS device_operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL UNIQUE,
    device_id TEXT NOT NULL,
    owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_id TEXT,
    task_run_id TEXT,
    action TEXT NOT NULL,
    params TEXT NOT NULL DEFAULT '{}',
    grant_version INTEGER NOT NULL CHECK (grant_version >= 1),
    status TEXT NOT NULL CHECK (status IN (
        'pending_confirmation', 'queued', 'running', 'completed',
        'failed', 'cancelled', 'unknown'
    )),
    result TEXT,
    error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (device_id, owner_user_id)
        REFERENCES devices(device_id, owner_user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_device_operations_owner
    ON device_operations(owner_user_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_device_operations_device
    ON device_operations(device_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_device_operations_task_run
    ON device_operations(owner_user_id, task_run_id);
UPDATE _schema_version SET version = 22;
