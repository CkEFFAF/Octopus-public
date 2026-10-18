import { useEffect, useState } from "react";
import { Button, Modal, Select } from "antd";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  threadSharesApi,
  type SharePreview,
  type ThreadShare,
} from "../../api/modules/threadShares";
import { parseApiError } from "../../utils/apiError";
import ShareList from "./ShareList";
import ShareMessages from "./ShareMessages";
import styles from "./sharing.module.less";

const errorKeys: Record<string, string> = {
  SHARE_INVALID: "invalid",
  SHARE_LIMIT: "limit",
  SHARE_STALE: "stale",
  SHARE_ORIGIN_REQUIRED: "originRequired",
};

export default function ShareManagementDialog({
  agentId,
  threadId,
  onClose,
}: {
  agentId: string;
  threadId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [preview, setPreview] = useState<SharePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [expiry, setExpiry] = useState<number | null>(30 * 86400);
  const [created, setCreated] = useState<ThreadShare | null>(null);
  const [revision, setRevision] = useState(0);
  const [listRevision, setListRevision] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setPreview(null);
    setError("");
    threadSharesApi
      .preview(agentId, threadId)
      .then((next) => {
        if (alive) setPreview(next);
      })
      .catch((cause) => {
        const code = parseApiError(cause)?.code;
        if (alive)
          setError(
            code && Object.prototype.hasOwnProperty.call(errorKeys, code)
              ? errorKeys[code]
              : "previewError",
          );
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [agentId, threadId, revision]);
  async function create() {
    if (!preview || creating) return;
    setCreating(true);
    setError("");
    setCreated(null);
    try {
      const share = await threadSharesApi.create(
        agentId,
        threadId,
        preview.preview_digest,
        expiry,
      );
      setCreated(share);
      setListRevision((value) => value + 1);
    } catch (cause) {
      const code = parseApiError(cause)?.code;
      setError(
        code && Object.prototype.hasOwnProperty.call(errorKeys, code)
          ? errorKeys[code]
          : "createError",
      );
      if (
        code === "SHARE_STALE" ||
        (cause instanceof Error && /\b409\b/.test(cause.message))
      ) {
        setPreview(null);
        setError("stale");
      }
    } finally {
      setCreating(false);
    }
  }
  return (
    <Modal
      open
      title={t("chatShare.title")}
      onCancel={onClose}
      footer={<Button onClick={onClose}>{t("common.close")}</Button>}
      width={760}
    >
      <p>{t("chatShare.explanation")}</p>
      <p className={styles.hint}>{t("chatShare.reviewWarning")}</p>
      {loading && <p role="status">{t("common.loading")}</p>}
      {error && <p role="alert">{t(`chatShare.errors.${error}`)}</p>}
      <Button
        disabled={loading || creating}
        onClick={() => setRevision((value) => value + 1)}
      >
        {t("chatShare.refreshPreview")}
      </Button>
      {preview && (
        <>
          <h3>{preview.title}</h3>
          <p>
            {t("chatShare.timezone")}: {preview.timezone}
          </p>
          <p>{t("chatShare.messageCount", { count: preview.message_count })}</p>
          <div className={styles.preview} aria-label={t("chatShare.preview")}>
            <ShareMessages messages={preview.messages} />
          </div>
        </>
      )}
      <div className={styles.row}>
        <label htmlFor="share-expiry">{t("chatShare.expiry")}</label>
        <Select<number | string>
          id="share-expiry"
          value={expiry == null ? "never" : expiry}
          onChange={(value) =>
            setExpiry(value === "never" ? null : Number(value))
          }
          options={[
            ...[1, 7, 30].map((days) => ({
              value: days * 86400,
              label: t("chatShare.days", { count: days }),
            })),
            { value: "never", label: t("chatShare.never") },
          ]}
          style={{ minWidth: 140 }}
        />
        <Button
          type="primary"
          loading={creating}
          disabled={!preview || loading}
          onClick={() => void create()}
        >
          {t("chatShare.create")}
        </Button>
      </div>
      {created && <p role="status">{t("chatShare.createdLink")}</p>}
      <ShareList
        agentId={agentId}
        threadId={threadId}
        revision={listRevision}
      />
      <p className={styles.hint}>{t("chatShare.closeExplanation")}</p>
      <Link to="/settings/thread-shares" onClick={onClose}>
        {t("chatShare.allLinks")}
      </Link>
    </Modal>
  );
}
