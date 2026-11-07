import { useRef } from "react";
import { useTranslation } from "react-i18next";
import { Activity, Clock3, ListChecks, MessageSquarePlus } from "lucide-react";
import { useElapsedSince } from "../../../hooks/useElapsedSeconds";
import type { SessionSnapshot } from "../hooks/sseHelpers";
import styles from "./ChatWorkStatus.module.less";

export default function ChatWorkStatus({
  onContinueChat,
  onShowProgress,
  phase,
  startedAt,
  retry,
}: {
  onContinueChat: () => void;
  onShowProgress?: () => void;
  phase?: string;
  startedAt?: number | null;
  retry?: SessionSnapshot["modelRetry"];
}) {
  const { t } = useTranslation();
  const mounted = useRef(Date.now());
  const elapsed = useElapsedSince(startedAt || mounted.current);
  const remaining = Math.max(
    0,
    Math.ceil((retry?.retry_at || 0) - Date.now() / 1000),
  );
  const known =
    phase &&
    [
      "preparing",
      "model",
      "thinking",
      "tools",
      "tool_running",
      "generating",
      "running",
      "waiting",
      "queued",
      "before_model",
      "model_streaming",
      "tool_executing",
      "after_model",
    ].includes(phase);
  const label = retry
    ? t(
        retry.phase === "waiting_retry"
          ? "chat.recovery.waiting"
          : "chat.recovery.retrying",
        {
          seconds: remaining,
          attempt:
            retry.phase === "waiting_retry" ? retry.attempt + 1 : retry.attempt,
          max: retry.max_attempts,
        },
      )
    : t(known ? `chat.steer.phase.${phase}` : "chat.flow.working", {
        defaultValue: t("chat.flow.working"),
      });
  return (
    <div className={styles.status} data-waiting={Boolean(retry)}>
      <div className={styles.summary}>
        {retry ? (
          <Clock3 size={17} aria-hidden />
        ) : (
          <Activity size={17} aria-hidden />
        )}
        <div>
          <strong role="status" aria-live="polite">
            {label}
          </strong>
          <span>{t("chat.flow.keepTalking")}</span>
        </div>
        <time aria-label={t("chat.flow.elapsed", { seconds: elapsed })}>
          {elapsed}s
        </time>
      </div>
      <div className={styles.actions}>
        {onShowProgress && (
          <button type="button" onClick={onShowProgress}>
            <ListChecks size={14} aria-hidden />
            {t("chat.backgroundUi.progress")}
          </button>
        )}
        <button type="button" onClick={onContinueChat}>
          <MessageSquarePlus size={14} aria-hidden />
          {t("chat.flow.anotherChat")}
        </button>
      </div>
    </div>
  );
}
