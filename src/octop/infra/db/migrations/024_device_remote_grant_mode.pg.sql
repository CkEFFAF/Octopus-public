-- 0005: remote grant mode for owner-driven permission expansion.
ALTER TABLE devices ADD COLUMN remote_grant_mode TEXT NOT NULL DEFAULT 'owner_auto';
UPDATE _schema_version SET version = 24;
