-- {owner_user_id} is validated by migrate.py before applying this migration.
BEGIN;
CREATE TABLE providers_owned (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    base_url TEXT,
    api_key TEXT,
    extra_json TEXT,
    models_json TEXT,
    note TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(user_id, name)
);
INSERT INTO providers_owned
SELECT id, {owner_user_id}, name, kind, base_url, api_key, extra_json,
       models_json, note, enabled, created_at, updated_at FROM providers;
DROP TABLE providers;
ALTER TABLE providers_owned RENAME TO providers;
UPDATE settings SET key = 'active_model.user.' || {owner_user_id}
WHERE key = 'active_model' AND {owner_user_id} IS NOT NULL;
DELETE FROM settings WHERE key = 'active_model';
INSERT INTO settings(key, value) SELECT 'providers.legacy_owner', CAST({owner_user_id} AS TEXT)
WHERE {owner_user_id} IS NOT NULL;
UPDATE _schema_version SET version = 25;
COMMIT;
