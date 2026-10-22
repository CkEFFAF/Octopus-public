import { CalendarClock } from "lucide-react";
import { Tooltip } from "antd";
import { useNavigate } from "react-router-dom";
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
  const navigate = useNavigate();
  const counts = value?.schedule_counts ?? {
    schedules: value?.schedules.filter((row) => !row.self_reminder).length ?? 0,
    reminders: value?.schedules.filter((row) => row.self_reminder).length ?? 0,
  };
  if (!owned) return null;
  const total = counts.schedules + counts.reminders;
  const recent = [...(value?.schedules ?? [])]
    .sort(
      (a, b) =>
        (a.next_run_at ?? Infinity) - (b.next_run_at ?? Infinity) ||
        (b.last_run_at ?? 0) - (a.last_run_at ?? 0),
    )
    .slice(0, 3);
  return (
    <span className={styles.expertScheduleBadges}>
      <Tooltip
        title={
          <div className={styles.expertTaskPreview}>
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
        }
      >
        <button
          type="button"
          aria-label={t("workspace0034.expertTaskPanel")}
          onKeyDown={(event) => event.stopPropagation()}
          onClick={(event) => {
            event.stopPropagation();
            const tab =
              counts.schedules === 0 && counts.reminders > 0
                ? "reminders"
                : "schedules";
            navigate(`/tasks?agent=${encodeURIComponent(agentId)}&tab=${tab}`);
          }}
        >
          <CalendarClock size={13} />
          {total > 0 && <span>{total}</span>}
        </button>
      </Tooltip>
    </span>
  );
}
