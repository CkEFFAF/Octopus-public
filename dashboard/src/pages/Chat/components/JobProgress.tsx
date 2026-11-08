import { useTranslation } from "react-i18next";
import styles from "./JobProgress.module.less";

export default function JobProgress({ value }: { value: unknown }) {
  const { t } = useTranslation();
  if (!value || typeof value !== "object") return null;
  const progress = value as Record<string, unknown>;
  if (progress.source !== "script_reported") return null;
  const percent =
    typeof progress.percent === "number" &&
    Number.isFinite(progress.percent) &&
    progress.percent >= 0 &&
    progress.percent <= 100
      ? progress.percent
      : null;
  const phase = typeof progress.phase === "string" ? progress.phase : "";
  const message = typeof progress.message === "string" ? progress.message : "";
  if (percent === null && !phase && !message) return null;
  return (
    <div className={styles.progress}>
      <span className={styles.heading}>
        <span>{phase || t("workspace0034.reportedProgress")}</span>
        {percent !== null && <b>{Math.round(percent * 10) / 10}%</b>}
      </span>
      {percent !== null && (
        <progress
          aria-label={t("workspace0034.reportedProgress")}
          max={100}
          value={percent}
        />
      )}
      {message && <small>{message}</small>}
    </div>
  );
}
