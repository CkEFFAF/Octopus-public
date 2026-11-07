import { useRef } from "react";
import { useTranslation } from "react-i18next";
import { Activity, Clock3, ListChecks, MessageSquarePlus } from "lucide-react";
import { useElapsedSince } from "../../../hooks/useElapsedSeconds";
import type { SessionSnapshot } from "../hooks/sseHelpers";
import type { ChatMessage } from "../hooks/sseHelpers";
import { toolProgress } from "../../../utils/toolProgress";
import styles from "./ChatWorkStatus.module.less";

export default function ChatWorkStatus({
  onContinueChat,
  onShowProgress,
  phase,
  startedAt,
  retry,
  currentTool,
}: {
  onContinueChat: () => void;
  onShowProgress?: () => void;
  phase?: string;
  startedAt?: number | null;
  retry?: SessionSnapshot["modelRetry"];
  currentTool?: ChatMessage["toolData"];
}) {
  const { t } = useTranslation();
  const mounted = useRef(Date.now());
  const elapsed = useElapsedSince(startedAt || mounted.current);
  const remaining = Math.max(
    0,
    Math.ceil((retry?.retry_at || 0) - Date.now() / 1000),
  );
  const feedback = currentTool
    ? toolProgress(
        currentTool.name,
        currentTool.arguments,
        currentTool.output,
        t,
        currentTool.errorCode ? "error" : undefined,
      )
    : null;
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
    : t(phase ? `chat.steer.phase.${phase}` : "chat.flow.working", {
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
          {feedback && (
            <span className={styles.currentAction} aria-live="polite">
              {feedback.action} · {feedback.outcome}
            </span>
          )}
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
