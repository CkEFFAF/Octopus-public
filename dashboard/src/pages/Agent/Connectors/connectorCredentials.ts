import type {
  ConnectorCatalogEntry,
  ConnectorInstanceDetail,
  ConnectorCredentialsPreview,
} from "../../../api/modules/connectors";

export function buildCredentials(
  entry: ConnectorCatalogEntry,
  values: Record<string, unknown>,
): Record<string, unknown> {
  const credentials: Record<string, unknown> = {};
  if (entry.auth_kind === "personal_token") {
    const token = String(values.token ?? "").trim();
    if (token) credentials.token = token;
  } else if (entry.auth_kind === "oauth2") {
    if (entry.kind === "qcc") {
      const api_key = String(values.api_key ?? "").trim();
      if (api_key) {
        credentials.api_key = api_key;
        return credentials;
      }
    }
    const access_token = String(values.access_token ?? "").trim();
    if (access_token && access_token !== "__configured__") {
      credentials.access_token = access_token;
    }
    if (values.refresh_token) credentials.refresh_token = values.refresh_token;
    if (values.expires_at) credentials.expires_at = values.expires_at;
    if (values.oauth_client_id)
      credentials.oauth_client_id = values.oauth_client_id;
    if (values.oauth_client_secret)
      credentials.oauth_client_secret = values.oauth_client_secret;
    if (values.openid) credentials.openid = values.openid;
  } else if (entry.auth_kind === "auth_code") {
    const code = String(values.auth_code ?? "").trim();
    if (code) credentials.code = code;
  } else if (entry.auth_kind === "api_key") {
    if (entry.kind === "feishu-cli") {
      if (values.app_id) credentials.app_id = String(values.app_id).trim();
      const app_secret = String(values.app_secret ?? "").trim();
      if (app_secret) credentials.app_secret = app_secret;
      if (values.default_as === "user") credentials.default_as = "user";
      if (values.cli_config_key) {
        credentials.cli_config_key = String(values.cli_config_key).trim();
      }
    } else if (entry.kind === "wecom-cli") {
      if (values.bot_id) credentials.bot_id = String(values.bot_id).trim();
      const bot_secret = String(values.bot_secret ?? "").trim();
      if (bot_secret) credentials.bot_secret = bot_secret;
    } else {
      const api_key = String(values.api_key ?? "").trim();
      if (api_key) credentials.api_key = api_key;
      if (entry.kind === "tencent-ima" && values.client_id) {
        credentials.client_id = values.client_id;
      }
      if (entry.kind === "tencent-lexiang" && values.client_id) {
        credentials.client_id = values.client_id;
      }
    }
  } else if (entry.auth_kind === "imap_app_password") {
    credentials.email = values.email;
    const password = String(values.password ?? "").trim();
    if (password) credentials.password = password;
    if (values.mail_provider) {
      credentials.mail_provider = values.mail_provider;
    }
    if (values.mail_provider === "custom") {
      if (values.imap_host) credentials.imap_host = values.imap_host;
      if (values.smtp_host) credentials.smtp_host = values.smtp_host;
      credentials.imap_port = values.imap_port ?? 993;
      credentials.smtp_port = values.smtp_port ?? 587;
    }
  } else if (entry.auth_kind === "api_credentials") {
    credentials.app_id = values.app_id;
    credentials.sdk_id = values.sdk_id;
    const secret_key = String(values.secret_key ?? "").trim();
    if (secret_key) credentials.secret_key = secret_key;
  } else if (entry.auth_kind === "custom_fields") {
    for (const field of entry.credential_fields ?? []) {
      const text = String(values[field.key] ?? "").trim();
      if (!text) continue;
      credentials[field.key] =
        field.field_type === "tags"
          ? text
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean)
          : text;
    }
  }
  return credentials;
}

export function previewToFormValues(
  entry: ConnectorCatalogEntry,
  detail: ConnectorInstanceDetail | null,
): Record<string, unknown> {
  if (!detail) {
    return {
      display_name: entry.name,
      description: entry.description,
      mail_provider: "qq",
      default_open: false,
      shared: false,
    };
  }
  const preview = detail.credentials_preview ?? {};
  const values: Record<string, unknown> = {
    display_name: detail.display_name || entry.name,
    description: detail.description || entry.description,
    default_open:
      detail.default_open === true || detail.config?.default_open === true,
    shared: detail.shared === true,
  };
  if (preview.email) values.email = preview.email;
  if (preview.mail_provider) values.mail_provider = preview.mail_provider;
  if (preview.imap_host) values.imap_host = preview.imap_host;
  if (preview.smtp_host) values.smtp_host = preview.smtp_host;
  if (preview.imap_port) values.imap_port = preview.imap_port;
  if (preview.smtp_port) values.smtp_port = preview.smtp_port;
  if (preview.bkn) values.bkn = preview.bkn;
  if (preview.knowledge_base_id)
    values.knowledge_base_id = preview.knowledge_base_id;
  if (preview.app_id) values.app_id = preview.app_id;
  if (preview.bot_id) values.bot_id = preview.bot_id;
  if (preview.cli_config_key) values.cli_config_key = preview.cli_config_key;
  if (preview.default_as === "user") values.default_as = "user";
  if (preview.client_id) values.client_id = preview.client_id;
  if (preview.sdk_id) values.sdk_id = preview.sdk_id;
  if (entry.auth_kind === "oauth2" && preview.oauth_configured) {
    values.access_token = "__configured__";
  }
  if (entry.auth_kind === "custom_fields") {
    for (const field of entry.credential_fields ?? []) {
      if (field.secret) continue;
      const value = preview[field.key];
      if (Array.isArray(value)) {
        values[field.key] = value.join(", ");
      } else if (value !== undefined && value !== null) {
        values[field.key] = value;
      }
    }
  }
  return values;
}

export function customCredentialConfigChanged(
  entry: ConnectorCatalogEntry,
  values: Record<string, unknown>,
  preview: ConnectorCredentialsPreview,
): boolean {
  if (entry.auth_kind === "imap_app_password") {
    const draft = buildCredentials(entry, values);
    return [
      "email",
      "mail_provider",
      "imap_host",
      "smtp_host",
      "imap_port",
      "smtp_port",
    ].some((key) => {
      if (draft[key] === undefined) return false;
      const stored =
        preview[key] ??
        (key === "imap_port" ? 993 : key === "smtp_port" ? 587 : "");
      return String(draft[key]).trim() !== String(stored).trim();
    });
  }
  if (entry.auth_kind !== "custom_fields") return false;
  return (entry.credential_fields ?? []).some((field) => {
    if (field.secret) return false;
    const current = String(values[field.key] ?? "").trim();
    const storedValue = preview[field.key];
    const stored = Array.isArray(storedValue)
      ? storedValue.join(", ")
      : String(storedValue ?? "").trim();
    return current !== stored;
  });
}
