import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Input } from "antd";
import { useTranslation } from "react-i18next";
import {
  threadSharesApi,
  type ThreadShare,
  type ThreadSharesPage,
} from "../../api/modules/threadShares";
import { copyText } from "../../utils/copyText";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import styles from "./sharing.module.less";

export function shareDate(value: number | null, timezone: string): string {
  if (value == null) return "";
  return new Intl.DateTimeFormat(undefined, {
    timeZone: timezone,
    dateStyle: "medium",
    timeStyle: "short",
  }).format(value * 1000);
}

export default function ShareList({
  agentId,
  threadId,
  revision = 0,
}: {
  agentId?: string;
  threadId?: string;
  revision?: number;
}) {
  const { t } = useTranslation();
  const timezone = useServerTimezone();
  const [page, setPage] = useState<ThreadSharesPage>({
    shares: [],
    next_before: null,
    has_more: false,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [acting, setActing] = useState<string | null>(null);
  const [feedback, setFeedback] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const alive = useRef(false);
  const generation = useRef(0);
  const scope = agentId && threadId ? { agentId, threadId } : undefined;
  const fetchPage = useCallback(
    async (before?: string | null) => {
      const version = generation.current;
      setLoading(true);
      setError(false);
      try {
        const next = await threadSharesApi.list(
          agentId && threadId ? { agentId, threadId } : undefined,
          before,
        );
        if (!alive.current || generation.current !== version) return;
        setPage((prev) => ({
          ...next,
          shares:
            before == null
              ? next.shares
              : [
                  ...new Map(
                    [...prev.shares, ...next.shares].map((share) => [
                      share.share_id,
                      share,
                    ]),
                  ).values(),
                ],
        }));
      } catch {
        if (alive.current && generation.current === version) setError(true);
      } finally {
        if (alive.current && generation.current === version) setLoading(false);
      }
    },
    [agentId, threadId],
  );
  useEffect(() => {
    alive.current = true;
    generation.current += 1;
    setPage({ shares: [], next_before: null, has_more: false });
    void fetchPage();
    return () => {
      alive.current = false;
      generation.current += 1;
    };
  }, [fetchPage, revision, refreshKey]);
  async function revoke(share: ThreadShare) {
    if (acting) return;
    setActing(share.share_id);
    setFeedback("");
    try {
      await threadSharesApi.revoke(share.share_id);
      if (alive.current) {
        setPage((prev) => ({
          ...prev,
          shares: prev.shares.map((row) =>
            row.share_id === share.share_id
              ? {
                  ...row,
                  status: "revoked",
                  revoked_at: Date.now() / 1000,
                  public_url: null,
                  public_path: null,
                }
              : row,
          ),
        }));
        setFeedback("closed");
      }
    } catch {
      if (alive.current) setFeedback("closeError");
    } finally {
      if (alive.current) setActing(null);
    }
  }
  async function copy(url: string) {
    setFeedback((await copyText(url)) ? "copied" : "copyError");
  }
  return (
    <section aria-label={t("chatShare.links")}>
      <div className={styles.row}>
        <h3>{t(scope ? "chatShare.threadLinks" : "chatShare.allLinks")}</h3>
        <Button
          disabled={loading}
          onClick={() => setRefreshKey((value) => value + 1)}
        >
          {t("common.refresh")}
        </Button>
      </div>
      {loading && <p role="status">{t("common.loading")}</p>}
      {error && <p role="alert">{t("chatShare.listError")}</p>}
      {feedback && (
        <p role={feedback.endsWith("Error") ? "alert" : "status"}>
          {t(`chatShare.${feedback}`)}
        </p>
      )}
      {!loading && !error && !page.shares.length && (
        <p>{t("chatShare.noLinks")}</p>
      )}
      <ul className={styles.list}>
        {page.shares.map((share) => {
          const status =
            share.status === "active" &&
            share.expires_at != null &&
            share.expires_at * 1000 <= Date.now()
              ? "expired"
              : share.status;
          return (
            <li key={share.share_id} className={styles.share}>
              <strong>{share.title}</strong>
              <p>
                {t(`chatShare.status.${status}`)} · {t("chatShare.created")}:{" "}
                {shareDate(share.created_at, timezone)}
              </p>
              <p>
                {t("chatShare.expires")}:{" "}
                {share.expires_at == null
                  ? t("chatShare.never")
                  : shareDate(share.expires_at, timezone)}
              </p>
              {status === "active" && share.public_url && (
                <Input
                  className={styles.link}
                  value={share.public_url}
                  readOnly
                  aria-label={t("chatShare.url")}
                />
              )}
              <div className={styles.row}>
                {status === "active" && share.public_url && (
                  <Button onClick={() => void copy(share.public_url!)}>
                    {t("chatShare.copy")}
                  </Button>
                )}
                {status !== "revoked" && (
                  <Button
                    loading={acting === share.share_id}
                    disabled={acting !== null}
                    onClick={() => void revoke(share)}
                  >
                    {t("chatShare.close")}
                  </Button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {page.has_more && (
        <Button
          disabled={loading || page.next_before == null}
          onClick={() => void fetchPage(page.next_before)}
        >
          {t("chatShare.more")}
        </Button>
      )}
    </section>
  );
}
