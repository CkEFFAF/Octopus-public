-- {owner_user_id} is validated by migrate.py before applying this migration.
ALTER TABLE providers ADD COLUMN user_id INTEGER;
UPDATE providers SET user_id = {owner_user_id};
ALTER TABLE providers ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE providers ADD CONSTRAINT providers_user_id_fkey
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE providers DROP CONSTRAINT IF EXISTS providers_name_key;
ALTER TABLE providers ADD CONSTRAINT providers_user_name_key UNIQUE(user_id, name);
UPDATE settings SET key = 'active_model.user.' || {owner_user_id}
WHERE key = 'active_model' AND {owner_user_id} IS NOT NULL;
DELETE FROM settings WHERE key = 'active_model';
INSERT INTO settings(key, value) SELECT 'providers.legacy_owner', CAST({owner_user_id} AS TEXT)
WHERE {owner_user_id} IS NOT NULL;
UPDATE _schema_version SET version = 25;
