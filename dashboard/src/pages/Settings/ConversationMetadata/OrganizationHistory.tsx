import { useCallback, useEffect, useState, useRef } from "react";
import {
  Alert,
  App,
  Button,
  Select,
  Space,
  Spin,
  Tag,
  Pagination,
  Empty,
} from "antd";
import { useTranslation } from "react-i18next";
import {
  conversationMetadataApi as api,
  type OrganizationAge,
  type OrganizationStatus,
  type OrganizationPage,
} from "../../../api/modules/conversationMetadata";
import FailureDiagnostics from "../../../components/FailureDiagnostics";
import { useServerTimezone } from "../../../hooks/useServerTimezone";
import { formatServerDateTime } from "../../../utils/formatMessageTime";
import { apiErrorMessage } from "../../../utils/apiError";
import styles from "./index.module.less";

export default function OrganizationHistory({
  age,
  status,
  onFilter,
  pending,
}: {
  age: OrganizationAge;
  status: OrganizationStatus;
  onFilter: (age: OrganizationAge, status: OrganizationStatus) => void;
  pending: boolean;
}) {
  const { t } = useTranslation();
  const translate = useRef(t);
  translate.current = t;
  const timezone = useServerTimezone();
  const { message } = App.useApp();
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<{
    key: string;
    value: OrganizationPage;
  } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [revision, setRevision] = useState(0);
  const key = `${age}:${status}:${offset}`;
  const current = page?.key === key ? page.value : null;
  useEffect(() => setOffset(0), [age, status]);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    let alive = true;
    let inFlight = false;
    async function load() {
      if (inFlight) return;
      inFlight = true;
      try {
        const value = await api.organizationPage(age, status, offset);
        if (alive) {
          if (offset > 0 && offset >= value.total) {
            setOffset(Math.floor(Math.max(0, value.total - 1) / 20) * 20);
            return;
          }
          setPage({ key, value });
          setError("");
        }
      } catch (e) {
        if (alive)
          setError(
            apiErrorMessage(
              e,
              translate.current("common.error"),
              translate.current,
            ),
          );
      } finally {
        inFlight = false;
      }
    }
    void load();
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 5000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [age, status, offset, key, revision]);
  const date = (value: number) =>
    value
      ? formatServerDateTime(value, timezone)
      : t("organizationHistory.never");
  return (
    <section className={styles.organizationHistory}>
      <h3>{t("organizationHistory.title")}</h3>
      <p className={styles.historyHint}>{t("organizationHistory.timeHint")}</p>
      <Space wrap className={styles.historyFilters}>
        <Select
          value={age}
          aria-label={t("organizationHistory.ageFilter")}
          onChange={(value) => {
            setOffset(0);
            onFilter(value, status);
          }}
          options={["all", "never", "d1", "d3", "d5", "d7", "older"].map(
            (value) => ({
              value,
              label: t(`organizationHistory.ages.${value}`),
            }),
          )}
        />
        <Select
          value={status}
          aria-label={t("organizationHistory.statusFilter")}
          onChange={(value) => {
            setOffset(0);
            onFilter(age, value);
          }}
          options={[
            "all",
            "never",
            "active",
            "ready",
            "failed",
            "cancelled",
          ].map((value) => ({
            value,
            label: t(`organizationHistory.status.${value}`),
          }))}
        />
        <Button onClick={refresh}>{t("common.refresh")}</Button>
        {current && (
          <span>
            {t("organizationHistory.matchCount", { count: current.total })}
          </span>
        )}
      </Space>
      {error && (
        <Alert
          type="error"
          showIcon
          message={error}
          action={<Button onClick={refresh}>{t("common.retry")}</Button>}
        />
      )}
      {!current && !error && <Spin />}
      {current && !current.items.length && (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("organizationHistory.empty")}
        />
      )}
      <div className={styles.organizationRows}>
        {current?.items.map((row) => {
          const failed = row.status === "failed";
          const active = ["queued", "retry", "running"].includes(row.status);
          const reason = failed
            ? t(
                `conversationMetadata.errors.${row.error_code}`,
                t("conversationMetadata.generationFailed"),
              )
            : "";
          return (
            <article
              key={`${row.agent_id}:${row.thread_id}`}
              className={styles.organizationRow}
            >
              <header>
                <div>
                  <strong title={row.title ?? ""}>
                    {row.title || t("conversationMetadata.untitled")}
                  </strong>
                  <small>{row.agent_name}</small>
                </div>
                <Tag
                  color={
                    failed
                      ? "error"
                      : active
                      ? "processing"
                      : row.status === "ready"
                      ? "success"
                      : "default"
                  }
                >
                  {t(
                    `organizationHistory.status.${
                      active ? "active" : row.status
                    }`,
                  )}
                </Tag>
              </header>
              <dl>
                <div>
                  <dt>{t("organizationHistory.lastSuccess")}</dt>
                  <dd>{date(row.last_success_at)}</dd>
                </div>
                <div>
                  <dt>{t("organizationHistory.lastAttempt")}</dt>
                  <dd>{date(row.last_attempt_at)}</dd>
                </div>
              </dl>
              <footer>
                {failed && (
                  <div className={styles.organizationFailure}>
                    <span>{reason}</span>
                    <FailureDiagnostics
                      summary={reason}
                      value={{
                        ...row.diagnostic,
                        code: row.error_code,
                        job_id: row.job_id,
                      }}
                    />
                  </div>
                )}
                <Button
                  size="small"
                  loading={busy === row.thread_id}
                  disabled={pending || active || Boolean(busy)}
                  onClick={async () => {
                    setBusy(row.thread_id);
                    try {
                      const job = await api.generate(
                        row.agent_id,
                        row.thread_id,
                        "brief",
                      );
                      setPage((old) =>
                        old
                          ? {
                              ...old,
                              value: {
                                ...old.value,
                                items: old.value.items.map((item) =>
                                  item.thread_id === row.thread_id
                                    ? {
                                        ...item,
                                        status: job.status,
                                        job_id: job.job_id,
                                      }
                                    : item,
                                ),
                              },
                            }
                          : old,
                      );
                      message.success(t("organizationHistory.queued"));
                      refresh();
                    } catch (e) {
                      message.error(apiErrorMessage(e, t("common.error"), t));
                    } finally {
                      setBusy("");
                    }
                  }}
                >
                  {t(
                    failed
                      ? "organizationHistory.retry"
                      : "organizationHistory.update",
                  )}
                </Button>
              </footer>
            </article>
          );
        })}
      </div>
      {current && current.total > 20 && (
        <Pagination
          size="small"
          current={offset / 20 + 1}
          total={current.total}
          pageSize={20}
          showSizeChanger={false}
          onChange={(value) => setOffset((value - 1) * 20)}
        />
      )}
    </section>
  );
}
