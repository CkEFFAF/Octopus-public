import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Space, Typography } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "../../../../api/request";

interface CatalogState {
  sources: {
    name: string;
    url: string;
    updated_at: number | null;
    stale: boolean;
    error: string | null;
  }[];
}

export default function CatalogStatus({
  onRefresh,
}: {
  onRefresh: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<CatalogState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const load = useCallback(async () => {
    try {
      setStatus(await request<CatalogState>("/providers/catalog"));
      setError(false);
    } catch {
      setError(true);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const refresh = async () => {
    setBusy(true);
    try {
      setStatus(
        await request<CatalogState>("/providers/catalog/refresh", {
          method: "POST",
        }),
      );
      await onRefresh();
      setError(false);
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Alert
      type={
        error || status?.sources.some((s) => s.stale || s.error)
          ? "warning"
          : "info"
      }
      message={t("models.catalogTitle")}
      description={
        <Space direction="vertical">
          <Typography.Text>{t("models.catalogDescription")}</Typography.Text>
          {status?.sources.map((source) => (
            <Typography.Text key={source.name}>
              <a href={source.url} target="_blank" rel="noreferrer">
                {source.name}
              </a>
              {" · "}
              {source.updated_at
                ? new Date(source.updated_at * 1000).toLocaleString()
                : t("models.catalogNever")}
              {(source.stale || source.error) &&
                ` · ${t("models.catalogStale")}`}
            </Typography.Text>
          ))}
          {error && (
            <Typography.Text type="danger">
              {t("models.catalogFailed")}
            </Typography.Text>
          )}
          <Button loading={busy} onClick={() => void refresh()}>
            {t("models.catalogRefresh")}
          </Button>
        </Space>
      }
      style={{ marginBottom: 16 }}
    />
  );
}
