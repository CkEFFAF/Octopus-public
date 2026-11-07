import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Clock3,
  CircleAlert,
  Loader2,
  RotateCcw,
  Settings,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ChatMessage } from "../hooks/useChat";
import { classifyChatStreamError } from "../../../utils/chatStreamError";
import styles from "./ChatResponseNotice.module.less";

export default function ChatResponseNotice({
  message,
  errorKey,
  summary,
  onRetry,
  onConfigure,
  configureLabel,
  children,
}: {
  message: ChatMessage;
  errorKey: string;
  summary: string;
  onRetry?: () => void | Promise<void>;
  onConfigure?: () => void;
  configureLabel?: string;
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  const category = classifyChatStreamError(errorKey);
  const limited = category === "stream_errors.rate_limit";
  const permanent =
    message.errorInfo?.code === "RESPONSE_RECOVERY_CONFLICT" ||
    [
      "stream_errors.auth",
      "stream_errors.insufficient_balance",
      "stream_errors.access_denied",
      "stream_errors.model_retired",
      "stream_errors.region_restricted",
      "stream_errors.context_length",
      "stream_errors.path_outside_root",
      "stream_errors.recursion_limit",
    ].includes(category || "");
  const diagnostic = message.errorInfo?.diagnostic as
    | Record<string, unknown>
    | undefined;
  const recovery = diagnostic?.response_recovery as
    | { retry_at?: number }
    | undefined;
  const hint =
    typeof diagnostic?.retry_after_seconds === "number"
      ? diagnostic.retry_after_seconds
      : 0;
  const retryAt = recovery?.retry_at || message.timestamp / 1000 + hint;
  const remainingNow = () =>
    Math.max(0, Math.ceil(retryAt - Date.now() / 1000));
  const [remaining, setRemaining] = useState(remainingNow);
  const [pending, setPending] = useState(false);
  const pendingRef = useRef(false);
  useEffect(() => {
    setRemaining(Math.max(0, Math.ceil(retryAt - Date.now() / 1000)));
    if (retryAt <= Date.now() / 1000) return;
    const timer = setInterval(() => {
      const seconds = Math.max(0, Math.ceil(retryAt - Date.now() / 1000));
      setRemaining(seconds);
      if (!seconds) clearInterval(timer);
    }, 1000);
    return () => clearInterval(timer);
  }, [retryAt]);
  const retry = async () => {
    if (!onRetry || remaining || pendingRef.current) return;
    pendingRef.current = true;
    setPending(true);
    try {
      await onRetry();
    } finally {
      pendingRef.current = false;
      setPending(false);
    }
  };
  return (
    <section
      className={styles.notice}
      data-tone={limited ? "waiting" : "error"}
      aria-label={t(
        limited ? "chat.recovery.busyTitle" : "chat.recovery.title",
      )}
    >
      <div className={styles.icon}>
        {limited ? (
          <Clock3 size={20} aria-hidden />
        ) : (
          <CircleAlert size={20} aria-hidden />
        )}
      </div>
      <div className={styles.content}>
        <strong>
          {t(limited ? "chat.recovery.busyTitle" : "chat.recovery.title")}
        </strong>
        <p>{limited ? t("chat.recovery.rateHint") : summary}</p>
        {!permanent && (
          <span className={styles.retained}>{t("chat.recovery.retained")}</span>
        )}
        {children}
        <div className={styles.actions}>
          {onRetry && !permanent && message.errorInfo?.retryable !== false && (
            <button
              type="button"
              onClick={() => void retry()}
              disabled={pending || remaining > 0}
              aria-busy={pending}
            >
              {pending ? (
                <Loader2 size={14} className={styles.spin} aria-hidden />
              ) : (
                <RotateCcw size={14} aria-hidden />
              )}
              {pending
                ? t("chat.recovery.resuming")
                : remaining
                ? t("chat.recovery.retryIn", { seconds: remaining })
                : t("chat.retry")}
            </button>
          )}
          {onConfigure && (
            <button type="button" onClick={onConfigure}>
              <Settings size={14} aria-hidden />
              {configureLabel}
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
