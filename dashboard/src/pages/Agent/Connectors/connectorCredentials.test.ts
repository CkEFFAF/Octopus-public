import { describe, expect, it } from "vitest";
import type {
  ConnectorCatalogEntry,
  ConnectorInstanceDetail,
} from "../../../api/modules/connectors";
import {
  buildCredentials,
  previewToFormValues,
  customCredentialConfigChanged,
} from "./connectorCredentials";

const entry = {
  kind: "qq-mail",
  auth_kind: "imap_app_password",
  name: "Personal mail",
  description: "IMAP / SMTP",
} as ConnectorCatalogEntry;

describe("custom mailbox configuration", () => {
  it("round-trips custom ports and preserves a saved password when left blank", () => {
    const detail = {
      display_name: "University",
      credentials_preview: {
        email: "student@university.example",
        mail_provider: "custom",
        imap_host: "imap.university.example",
        smtp_host: "smtp.university.example",
        imap_port: 1993,
        smtp_port: 465,
      },
    } as ConnectorInstanceDetail;
    const values = previewToFormValues(entry, detail);
    const credentials = buildCredentials(entry, values);
    expect(credentials).toMatchObject(detail.credentials_preview);
    expect(credentials).not.toHaveProperty("password");
    expect(
      customCredentialConfigChanged(entry, values, detail.credentials_preview!),
    ).toBe(false);
    expect(
      customCredentialConfigChanged(
        entry,
        { ...values, smtp_port: 587 },
        detail.credentials_preview!,
      ),
    ).toBe(true);
  });

  it("defaults custom TLS ports and excludes stale custom ports for preset providers", () => {
    expect(buildCredentials(entry, { mail_provider: "custom" })).toMatchObject({
      imap_port: 993,
      smtp_port: 587,
    });
    const preset = buildCredentials(entry, {
      mail_provider: "qq",
      imap_port: 1993,
      smtp_port: 465,
    });
    expect(preset).not.toHaveProperty("smtp_port");
    expect(preset).not.toHaveProperty("imap_port");
  });
});
