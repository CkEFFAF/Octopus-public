import { Tooltip } from "antd";
import { Flame, Activity, Layers, MessageCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ThreadHeat } from "../../../api/modules/octopThreads";
import styles from "./SessionHeat.module.less";
export default function SessionHeat({ heat }: { heat?: ThreadHeat }) {
  const { t } = useTranslation();
  if (!heat || heat.level === "quiet") return null;
  const Icon =
    heat.level === "running"
      ? Layers
      : heat.level === "attention"
      ? MessageCircle
      : heat.level === "hot"
      ? Flame
      : Activity;
  return (
    <Tooltip
      trigger={["hover", "focus"]}
      title={
        <span>
          {t("sessionHeat.score", { score: heat.score })}
          <br />
          {t("sessionHeat.inputs", { count: heat.interactions_24h })}
          <br />
          {t("sessionHeat.weeklyInputs", { count: heat.interactions_7d })}
          <br />
          {t("sessionHeat.tasks", { count: heat.work_7d })}
          <br />
          {t("sessionHeat.background", { count: heat.background_count })}
        </span>
      }
    >
      <span
        tabIndex={0}
        className={`${styles.badge} ${styles[heat.level]}`}
        aria-label={t("sessionHeat.score", { score: heat.score })}
      >
        <Icon size={11} aria-hidden />
        <span>{t(`sessionHeat.level.${heat.level}`)}</span>
      </span>
    </Tooltip>
  );
}
