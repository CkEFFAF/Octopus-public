import { Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import type { ReactElement } from "react";
import type { Session } from "../hooks/useSessions";
import { useSessionActivity } from "../hooks/useSidebarActivity";
import { useServerTimezone } from "../../../hooks/useServerTimezone";
import { formatMessageTime } from "../../../utils/formatMessageTime";
import { localizedPreview, previewText } from "../utils/sessionPreview";
import styles from "../index.module.less";

export default function SessionPreview({
  session,
  children,
}: {
  session: Session;
  children: ReactElement;
}) {
  const { t, i18n } = useTranslation();
  const timezone = useServerTimezone();
  const { working, background, schedules, metadata } = useSessionActivity(
    session.id,
  );
  const language = i18n?.resolvedLanguage ?? i18n?.language ?? "en";
  const meta =
    metadata &&
    (!session.metadata ||
      metadata.generated_at >= session.metadata.generated_at)
      ? metadata
      : session.metadata;
  const readable = (value?: string) => localizedPreview(value, language);
  const topic = readable(meta?.one_liner);
  const progress =
    readable(meta?.current_progress) ||
    readable(meta?.recent_events?.at(-1)) ||
    readable(meta?.stage);
  const blocker = readable(meta?.blocker);
  const next = readable(meta?.next_action);
  const mismatch = Boolean(meta?.one_liner && !topic);
  return (
    <Tooltip
      trigger={["hover", "focus"]}
      placement="right"
      color="var(--fn-bg-elevated)"
      overlayClassName={styles.sessionScheduleTooltip}
      overlayInnerStyle={{
        padding: 14,
        border: "1px solid var(--fn-border-secondary)",
        color: "var(--fn-text-primary)",
        boxShadow: "0 6px 24px rgb(0 0 0 / 12%)",
      }}
      title={
        <div className={styles.sessionOverviewPreview}>
          <strong>{previewText(topic || session.name, 64)}</strong>
          <div className={styles.previewState}>
            {working
              ? t("chat.sessionWorkingShort")
              : t(
                  `conversationMetadata.states.${
                    meta?.display_state || "unknown"
                  }`,
                )}
            {background.length > 0 && (
              <span>
                {t("sessionPreview.backgroundCount", {
                  count: background.length,
                })}
              </span>
            )}
            {schedules.length > 0 && (
              <span>
                {t("chat.sessionSchedules", { count: schedules.length })}
              </span>
            )}
          </div>
          <dl>
            <div>
              <dt>{t("sessionPreview.progress")}</dt>
              <dd>
                {progress ||
                  t(
                    working
                      ? "sessionPreview.runningNoSummary"
                      : "sessionPreview.noProgress",
                  )}
              </dd>
            </div>
            {(blocker || next) && (
              <div>
                <dt>
                  {t(
                    blocker ? "sessionPreview.blocker" : "sessionPreview.next",
                  )}
                </dt>
                <dd>{blocker || next}</dd>
              </div>
            )}
          </dl>
          <footer>
            {mismatch ? (
              t("sessionPreview.languageHint")
            ) : !meta ? (
              t("conversationMetadata.notGenerated")
            ) : (
              <>
                {meta.freshness === "stale" &&
                  `${t("conversationMetadata.freshness.stale")} · `}
                {meta.generated_at
                  ? formatMessageTime(meta.generated_at * 1000, timezone)
                  : t("conversationMetadata.notGenerated")}
              </>
            )}
          </footer>
        </div>
      }
    >
      {children}
    </Tooltip>
  );
}
