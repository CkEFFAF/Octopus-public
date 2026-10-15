-- 0017 device ZDU version fields (cron kind/meta ensured in _ensure_cron_jobs_schema)
ALTER TABLE devices ADD COLUMN software_version TEXT;
ALTER TABLE devices ADD COLUMN update_status TEXT;
UPDATE _schema_version SET version = 27;
