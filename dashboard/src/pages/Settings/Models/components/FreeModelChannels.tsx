import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  App,
  Button,
  Collapse,
  Form,
  Input,
  Modal,
  Space,
  Tag,
} from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../../../../api/request";
import { apiErrorMessage } from "../../../../utils/apiError";
import { fetchProviderModels } from "../providerApi";
import type { ProviderRow } from "../useProviders";

type Entry = {
  id: string;
  name: string;
  base_url: string;
  signup_url: string;
  models: string[];
};
export default function FreeModelChannels({
  providers,
  onSaved,
}: {
  providers: ProviderRow[];
  onSaved: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [entries, setEntries] = useState<Entry[]>([]);
  const [error, setError] = useState("");
  const [entry, setEntry] = useState<Entry | null>(null);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(
    () =>
      request<{ items: Entry[] }>("/providers/free-hub")
        .then((r) => {
          setEntries(r.items);
          setError("");
        })
        .catch((e) => setError(apiErrorMessage(e, t("common.error"), t))),
    [t],
  );
  useEffect(() => {
    void load();
  }, [load]);
  const our = providers.find((p) => p.name === "Our Free Model");
  return (
    <section
      style={{
        margin: "16px 0",
        padding: 16,
        border: "1px solid var(--fn-border-secondary)",
        borderRadius: 12,
      }}
    >
      <h3>{t("models.freeChannels")}</h3>
      <p>{t("models.freeListingHint")}</p>
      {error && <Alert type="error" message={error} />}
      {our && (
        <Space wrap>
          <span>
            Our Free Model ·{" "}
            {t("models.freeCounts", {
              total: our.models.length,
              enabled: our.models.filter((m) => m.enabled).length,
            })}
          </span>
          <Button
            loading={busy}
            onClick={async () => {
              setBusy(true);
              try {
                const result = await fetchProviderModels({
                  kind: our.kind,
                  name: our.name,
                  base_url: our.base_url,
                  api_key: our.api_key || undefined,
                });
                if (!result.ok || !result.models?.length)
                  throw new Error(result.error || t("models.catalogFailed"));
                const models = result.models.map((model) => ({
                  ...our.models.find((m) => m.id === model.id),
                  ...model,
                  enabled: true,
                }));
                await request(`/providers/${our.id}`, {
                  method: "PATCH",
                  body: JSON.stringify({ models }),
                });
                await onSaved();
                message.success(
                  t("models.freeSynced", { count: models.length }),
                );
              } catch (e) {
                setError(apiErrorMessage(e, t("common.error"), t));
              } finally {
                setBusy(false);
              }
            }}
          >
            {t("models.syncAllFree")}
          </Button>
        </Space>
      )}
      <Collapse
        style={{ marginTop: 12 }}
        items={[
          {
            key: "hub",
            label: `dsh-free-models-hub · ${entries.length}`,
            children: (
              <Space direction="vertical" style={{ width: "100%" }}>
                <Button onClick={() => void load()}>
                  {t("common.refresh")}
                </Button>
                {entries.map((row) => (
                  <section
                    key={row.id}
                    style={{
                      padding: 12,
                      width: "100%",
                      borderBottom: "1px solid var(--fn-border-secondary)",
                    }}
                  >
                    <strong>{row.name}</strong>{" "}
                    <Tag>{t("models.keyRequired")}</Tag>
                    <p style={{ overflowWrap: "anywhere" }}>{row.base_url}</p>
                    <p style={{ overflowWrap: "anywhere" }}>
                      {row.models.join(" · ")}
                    </p>
                    <Space wrap>
                      {row.signup_url && (
                        <a
                          href={row.signup_url}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {t("models.applyFreeKey")}
                        </a>
                      )}
                      <Button
                        onClick={() => {
                          setEntry(row);
                          setKey("");
                        }}
                      >
                        {t("models.configureFree")}
                      </Button>
                    </Space>
                  </section>
                ))}
              </Space>
            ),
          },
        ]}
      />
      <Modal
        open={!!entry}
        title={entry?.name}
        onCancel={() => {
          setEntry(null);
          setKey("");
        }}
        confirmLoading={busy}
        okButtonProps={{ disabled: !key.trim() }}
        onOk={async () => {
          if (!entry || !key.trim()) return;
          setBusy(true);
          try {
            await request("/providers", {
              method: "POST",
              body: JSON.stringify({
                name: `Free Hub / ${entry.name}`,
                kind: "openai",
                base_url: entry.base_url,
                api_key: key.trim(),
                models: entry.models.map((id) => ({
                  id,
                  name: id,
                  enabled: true,
                  input: ["text"],
                })),
              }),
            });
            setEntry(null);
            setKey("");
            await onSaved();
          } catch (e) {
            message.error(apiErrorMessage(e, t("common.error"), t));
          } finally {
            setBusy(false);
          }
        }}
      >
        <p>{t("models.freeKeyPrivacy")}</p>
        <Form.Item label="API Key">
          <Input.Password
            value={key}
            onChange={(e) => setKey(e.target.value)}
            autoComplete="off"
          />
        </Form.Item>
      </Modal>
    </section>
  );
}
