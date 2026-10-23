import { useState } from "react";
import SidebarTaskDialog from "./SidebarTaskDialog";
import { Clock3, LoaderCircle, Terminal } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Tooltip } from "antd";
import { useSessionActivity } from "../hooks/useSidebarActivity";
import { formatServerDateTime } from "../../../utils/formatMessageTime";
import styles from "../index.module.less";

export default function SessionActivity({ threadId }: { threadId: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const { working, schedules, agentId, background } =
    useSessionActivity(threadId);
  const scheduled = schedules.some(
    (row) =>
      row.enabled &&
      ["scheduled", "waiting_event"].includes(row.scheduler_state),
  );
  const upcoming = (row: (typeof schedules)[number]) =>
    row.enabled && row.scheduler_state === "scheduled" && !!row.next_run_at;
  const recent = [...schedules]
    .sort((a, b) => {
      const aNext = upcoming(a);
      const bNext = upcoming(b);
      if (aNext !== bNext) return aNext ? -1 : 1;
      if (aNext && bNext) return a.next_run_at! - b.next_run_at!;
      return (
        (b.last_run_at ?? b.created_at ?? 0) -
        (a.last_run_at ?? a.created_at ?? 0)
      );
    })
    .slice(0, 2);
  const openTasks = () => {
    if (agentId) setOpen(true);
  };
  return (
    <span className={styles.sessionActivity}>
      {agentId && (
        <SidebarTaskDialog
          agentId={agentId}
          threadId={threadId}
          open={open}
          onClose={() => setOpen(false)}
          initialTab={
            background.length
              ? "background"
              : recent[0]?.self_reminder
              ? "reminders"
              : "schedules"
          }
        />
      )}
      {working && (
        <span
          className={styles.sessionWorkingBadge}
          title={t("chat.sessionWorking")}
        >
          <LoaderCircle size={12} aria-hidden />
          <span>{t("chat.sessionWorkingShort")}</span>
        </span>
      )}
      {background.length > 0 && (
        <button
          type="button"
          className={styles.sessionScheduleBadge}
          onClick={(event) => {
            event.stopPropagation();
            openTasks();
          }}
          onKeyDown={(event) => event.stopPropagation()}
          aria-label={t("workspace0034.backgroundSummary")}
        >
          <Terminal size={13} aria-hidden /> {background.length}
        </button>
      )}
      {schedules.length > 0 && (
        <Tooltip
          title={
            <div className={styles.sessionSchedulePreview}>
              <ul>
                {recent.map((row) => (
                  <li key={row.id}>
                    <strong>{row.name}</strong>
                    <span>
                      {upcoming(row)
                        ? t("octopus.nextRun")
                        : row.last_run_at
                        ? t("chat.sessionScheduleLastRun")
                        : t(
                            `workspace0034.scheduleState.${row.scheduler_state}`,
                          )}
                      {(upcoming(row) ? row.next_run_at : row.last_run_at)
                        ? ` · ${formatServerDateTime(
                            (upcoming(row)
                              ? row.next_run_at
                              : row.last_run_at)!,
                            row.timezone,
                          )}`
                        : ""}
                    </span>
                    {(row.next_run_at || row.last_run_at) && (
                      <small>{row.timezone}</small>
                    )}
                  </li>
                ))}
              </ul>
              <footer>
                {t("chat.sessionScheduleOpenWorkbench", {
                  count: schedules.length,
                })}
              </footer>
            </div>
          }
          trigger={["hover", "focus"]}
          placement="right"
          color="var(--fn-bg-elevated)"
          overlayClassName={styles.sessionScheduleTooltip}
          overlayInnerStyle={{
            padding: 12,
            border: "1px solid var(--fn-border-secondary)",
            color: "var(--fn-text-primary)",
            boxShadow: "0 6px 24px rgb(0 0 0 / 12%)",
          }}
        >
          <span
            role="button"
            tabIndex={0}
            onClick={(event) => {
              event.stopPropagation();
              openTasks();
            }}
            onKeyDown={(event) => {
              event.stopPropagation();
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                openTasks();
              }
            }}
            className={styles.sessionScheduleBadge}
            data-scheduled={scheduled}
            aria-label={t("chat.sessionSchedules", { count: schedules.length })}
          >
            <Clock3 size={13} aria-hidden />
            {schedules.length > 1 ? schedules.length : null}
          </span>
        </Tooltip>
      )}
    </span>
  );
}
