import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  readPublicThreadShare,
  type PublicThreadShare,
} from "../../api/modules/publicThreadShares";
import ShareMessages from "../../components/Sharing/ShareMessages";
import styles from "../../components/Sharing/sharing.module.less";

function PublicShareContent({ token }: { token: string }) {
  const { t } = useTranslation();
  const [snapshot, setSnapshot] = useState<PublicThreadShare | null>(null);
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState(false);
  const active = useRef(false);
  const pending = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    if (pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    setLoading(true);
    try {
      const next = await readPublicThreadShare(token, controller.signal);
      if (active.current && !controller.signal.aborted) {
        setSnapshot(next);
        setUnavailable(false);
      }
    } catch {
      if (active.current && !controller.signal.aborted) {
        setSnapshot(null);
        setUnavailable(true);
      }
    } finally {
      if (pending.current === controller) pending.current = null;
      if (active.current && !controller.signal.aborted) setLoading(false);
    }
  }, [token]);
  useEffect(() => {
    active.current = true;
    void refresh();
    const revalidate = () => {
      if (document.visibilityState !== "hidden") void refresh();
    };
    const timer = window.setInterval(revalidate, 30000);
    window.addEventListener("focus", revalidate);
    window.addEventListener("online", revalidate);
    document.addEventListener("visibilitychange", revalidate);
    const previous = ["robots", "referrer"].map((name) => {
      const existing = document.head.querySelector<HTMLMetaElement>(
        `meta[name="${name}"]`,
      );
      const node = existing ?? document.createElement("meta");
      const content = existing?.content;
      node.name = name;
      node.content =
        name === "robots" ? "noindex, nofollow, noarchive" : "no-referrer";
      if (!existing) document.head.appendChild(node);
      return { node, existing, content };
    });
    return () => {
      active.current = false;
      pending.current?.abort();
      pending.current = null;
      window.clearInterval(timer);
      window.removeEventListener("focus", revalidate);
      window.removeEventListener("online", revalidate);
      document.removeEventListener("visibilitychange", revalidate);
      previous.forEach(({ node, existing, content }) => {
        if (existing) node.content = content ?? "";
        else node.remove();
      });
    };
  }, [refresh]);
  useEffect(() => {
    if (snapshot?.expires_at == null) return;
    const remaining = snapshot.expires_at * 1000 - Date.now();
    const timer = window.setTimeout(
      () => {
        setSnapshot(null);
        setUnavailable(true);
        void refresh();
      },
      Math.max(0, Math.min(remaining, 2147483647)),
    );
    return () => window.clearTimeout(timer);
  }, [snapshot, refresh]);
  return (
    <main className={styles.page}>
      <p>{t("chatShare.publicNotice")}</p>
      {loading && <p role="status">{t("common.loading")}</p>}
      {unavailable && (
        <div role="alert">
          <h1>{t("chatShare.unavailable")}</h1>
          <p>{t("chatShare.unavailableHint")}</p>
          <button type="button" onClick={() => void refresh()}>
            {t("common.retry")}
          </button>
        </div>
      )}
      {snapshot && (
        <>
          <h1>{snapshot.title}</h1>
          <p className={styles.hint}>
            {t("chatShare.created")}:{" "}
            {new Date(snapshot.created_at * 1000).toLocaleString(undefined, {
              timeZone: snapshot.timezone,
            })}{" "}
            · {t("chatShare.expires")}:{" "}
            {snapshot.expires_at == null
              ? t("chatShare.never")
              : new Date(snapshot.expires_at * 1000).toLocaleString(undefined, {
                  timeZone: snapshot.timezone,
                })}
          </p>
          <ShareMessages messages={snapshot.messages} />
        </>
      )}
    </main>
  );
}

export default function PublicSharePage() {
  const { token = "" } = useParams<{ token: string }>();
  return <PublicShareContent key={token} token={token} />;
}
