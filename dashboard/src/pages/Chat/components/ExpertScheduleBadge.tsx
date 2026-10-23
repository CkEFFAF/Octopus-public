import { useState } from "react";
import SidebarTaskDialog from "./SidebarTaskDialog";
import { CalendarClock } from "lucide-react";
import { Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import { useSidebarActivity } from "../hooks/useSidebarActivity";
import { formatServerDateTime } from "../../../utils/formatMessageTime";
import styles from "../index.module.less";

export default function ExpertScheduleBadge({
  agentId,
  owned = true,
}: {
  agentId: string;
  owned?: boolean;
}) {
  const value = useSidebarActivity()[agentId];
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const working = Boolean(value?.working_threads?.length);
  const counts = value?.schedule_counts ?? {
    schedules: value?.schedules.filter((row) => !row.self_reminder).length ?? 0,
    reminders: value?.schedules.filter((row) => row.self_reminder).length ?? 0,
  };
  if (!owned) return null;
  const background = value?.background_tasks?.length ?? 0;
  const total = counts.schedules + counts.reminders + background;
  const recent = [...(value?.schedules ?? [])]
    .sort(
      (a, b) =>
        (a.next_run_at ?? Infinity) - (b.next_run_at ?? Infinity) ||
        (b.last_run_at ?? 0) - (a.last_run_at ?? 0),
    )
    .slice(0, 3);
  return (
    <span className={styles.expertScheduleBadges}>
      <SidebarTaskDialog
        agentId={agentId}
        open={open}
        onClose={() => setOpen(false)}
        initialTab={
          counts.schedules === 0 && counts.reminders > 0
            ? "reminders"
            : "schedules"
        }
      />
      <Tooltip
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
        title={
          !open && (
            <div className={styles.sessionSchedulePreview}>
              <strong>{t("workspace0034.expertTaskPanel")}</strong>
              <p>{t("workspace0034.scheduleSummary", counts)}</p>
              {recent.length > 0 ? (
                <ul>
                  {recent.map((row) => (
                    <li key={row.id}>
                      <span>{row.name}</span>
                      <small>
                        {row.next_run_at
                          ? t("workspace0034.nextAt", {
                              time: formatServerDateTime(
                                row.next_run_at,
                                row.timezone,
                              ),
                            })
                          : t(
                              `workspace0034.scheduleState.${row.scheduler_state}`,
                            )}
                      </small>
                    </li>
                  ))}
                </ul>
              ) : (
                !total && <p>{t("workspace0034.scheduleEmpty")}</p>
              )}
            </div>
          )
        }
      >
        <button
          data-task-state={working ? "running" : total ? "scheduled" : "empty"}
          title={t(
            working
              ? "chat.sessionWorking"
              : total
              ? "workspace0034.configuredTasks"
              : "workspace0034.expertTaskPanel",
            { count: total },
          )}
          type="button"
          aria-label={t("workspace0034.expertTaskPanel")}
          onKeyDown={(event) => event.stopPropagation()}
          onClick={(event) => {
            event.stopPropagation();
            setOpen(true);
          }}
        >
          <CalendarClock size={13} />
          {total > 0 && <span>{total}</span>}
        </button>
      </Tooltip>
    </span>
  );
}
