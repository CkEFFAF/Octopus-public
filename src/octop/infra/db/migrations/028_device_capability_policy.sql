-- 0025 S0: device capability policy pack (MCP / Skill scopes)
ALTER TABLE devices ADD COLUMN capability_policy_json TEXT;
UPDATE _schema_version SET version = 28;
