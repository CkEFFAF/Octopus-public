import { Popover } from "antd";
import { Route } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ModelRouteDecision } from "../../../api/modules/modelRouting";
import styles from "./ModelRouteNotice.module.less";

export default function ModelRouteNotice({
  route,
}: {
  route: ModelRouteDecision;
}) {
  const { t } = useTranslation();
  const model = t("modelRouting.currentModel", {
    model: route.model || t("modelRouting.noModel"),
  });
  return (
    <Popover
      trigger="click"
      placement="topRight"
      title={t("modelRouting.routeDetails")}
      content={
        <div className={styles.notice}>
          <strong>{model}</strong>
          <span>{t(`modelRouting.tasks.${route.task}`)}</span>
          <span>
            {t(`modelRouting.reasons.${route.reason}`, {
              defaultValue: t("modelRouting.reasons.account_default"),
            })}
          </span>
        </div>
      }
    >
      <button
        type="button"
        title={t("modelRouting.routeDetails")}
        aria-label={`${t("modelRouting.routeDetails")}: ${model}`}
      >
        <Route size={15} aria-hidden />
      </button>
    </Popover>
  );
}
