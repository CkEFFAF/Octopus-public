import { Clock3, LoaderCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Tooltip } from "antd";
import { useSessionActivity } from "../hooks/useSidebarActivity";
import { formatServerDateTime } from "../../../utils/formatMessageTime";
import styles from "../index.module.less";

export default function SessionActivity({ threadId }: { threadId: string }) {
  const { t } = useTranslation();
  const { working, schedules } = useSessionActivity(threadId);
  const scheduled = schedules.some(
    (row) =>
      row.enabled &&
      ["scheduled", "waiting_event"].includes(row.scheduler_state),
  );
  const details = schedules
    .map((row) => {
      const state = t(`workspace0034.scheduleState.${row.scheduler_state}`);
      const next = row.next_run_at
        ? ` · ${t("octopus.nextRun")}: ${formatServerDateTime(
            row.next_run_at,
            row.timezone,
          )} (${row.timezone})`
        : "";
      return `${row.name} · ${state}${next}`;
    })
    .join("\n");
  return (
    <span className={styles.sessionActivity}>
      {working && (
        <span
          className={styles.sessionWorkingBadge}
          title={t("chat.sessionWorking")}
        >
          <LoaderCircle size={12} aria-hidden />
          <span>{t("chat.sessionWorkingShort")}</span>
        </span>
      )}
      {schedules.length > 0 && (
        <Tooltip
          title={<span style={{ whiteSpace: "pre-line" }}>{details}</span>}
          trigger={["hover", "focus"]}
        >
          <span
            tabIndex={0}
            onKeyDown={(event) => event.stopPropagation()}
            className={styles.sessionScheduleBadge}
            data-scheduled={scheduled}
            aria-label={t("chat.sessionSchedules", { count: schedules.length })}
            title={details}
          >
            <Clock3 size={13} aria-hidden />
            {schedules.length > 1 ? schedules.length : null}
          </span>
        </Tooltip>
      )}
    </span>
  );
}
