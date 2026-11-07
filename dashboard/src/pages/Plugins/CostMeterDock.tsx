import { useState } from "react";
import { Link } from "react-router-dom";
import { Gauge, Settings2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button, Popover } from "antd";
import { useCostMeter } from "./useCostMeter";
import { CostMeterView, duration } from "./CostMeter";
import CostMeterSettings from "./CostMeterSettings";
import styles from "./index.module.less";

export default function CostMeterDock() {
  const { t } = useTranslation();
  const { state, error, busy, refresh, now } = useCostMeter();
  const [settings, setSettings] = useState(false);
  if (
    !state?.installation.installed ||
    !state.installation.enabled ||
    !state.installation.show_in_chat
  )
    return null;
  const stale = error || state.go.status === "error";
  return (
    <>
      <div className={styles.chatStrip}>
        <Popover
          trigger="click"
          placement="topRight"
          overlayClassName={styles.dockPopover}
          content={
            <>
              <CostMeterView
                state={state}
                now={now}
                busy={busy}
                onRefresh={() => void refresh(true)}
                onSettings={() => setSettings(true)}
                connectionError={error}
              />
              <Link to="/plugins?tab=installed" className={styles.manageLink}>
                {t("pluginMarket.manage")}
              </Link>
            </>
          }
        >
          <button className={styles.stripButton}>
            <Gauge size={13} />
            <span
              className={
                state.peak.in_peak ? styles.peakText : styles.offpeakText
              }
            >
              DeepSeek{" "}
              {t(
                state.peak.in_peak
                  ? "pluginMarket.peak"
                  : "pluginMarket.offpeak",
              )}
            </span>
            <span className={styles.stripCountdown}>
              {duration(Date.parse(state.peak.next_change_at) - now)}
            </span>
            {stale ? (
              <span role="status">{t("pluginMarket.refreshFailed")}</span>
            ) : (
              state.go.rolling && (
                <span>Go {state.go.rolling.percent.toFixed(0)}%</span>
              )
            )}
            <span className={styles.stripDetails}>
              {t("pluginMarket.details")}
            </span>
          </button>
        </Popover>
        <Button
          size="small"
          type="text"
          icon={<Settings2 size={12} />}
          aria-label={t("pluginMarket.configure")}
          onClick={() => setSettings(true)}
        />
      </div>
      <CostMeterSettings open={settings} onClose={() => setSettings(false)} />
    </>
  );
}
