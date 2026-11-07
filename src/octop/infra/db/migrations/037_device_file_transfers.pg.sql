-- 0044 audited device P2P file transfer (G4): authoritative transfer sessions.
-- Tip max was 035; 0043 proposes 036 on another branch — this uses 037 (DEC-0044-15).
CREATE TABLE IF NOT EXISTS device_file_transfers (
  transfer_id TEXT PRIMARY KEY,
  request_id TEXT,
  owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  actor_user_id INTEGER,
  agent_id TEXT,
  source_device_id TEXT NOT NULL,
  source_root_id TEXT NOT NULL,
  source_path TEXT NOT NULL,
  source_grant_version INTEGER NOT NULL,
  target_device_id TEXT NOT NULL,
  target_root_id TEXT NOT NULL,
  target_path TEXT NOT NULL,
  target_grant_version INTEGER NOT NULL,
  size BIGINT,
  sha256 TEXT,
  policy_version INTEGER NOT NULL DEFAULT 1,
  ticket_hash TEXT,
  ticket_expires_at DOUBLE PRECISION,
  ticket_consumed_at DOUBLE PRECISION,
  preferred_transport TEXT NOT NULL DEFAULT 'auto',
  actual_transport TEXT,
  status TEXT NOT NULL,
  bytes_done BIGINT NOT NULL DEFAULT 0,
  fallback_reason TEXT,
  failure_direction TEXT,
  error_code TEXT,
  audit_id TEXT NOT NULL,
  attempts_json TEXT NOT NULL DEFAULT '[]',
  receipts_json TEXT NOT NULL DEFAULT '{}',
  operation_id TEXT,
  overwrite BOOLEAN NOT NULL DEFAULT FALSE,
  revoked_at DOUBLE PRECISION,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_device_transfers_owner_request
  ON device_file_transfers(owner_user_id, request_id)
  WHERE request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_device_transfers_owner_created
  ON device_file_transfers(owner_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_device_transfers_operation
  ON device_file_transfers(operation_id);
UPDATE _schema_version SET version=37;
