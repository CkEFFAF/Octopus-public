import { Alert, Button, Progress, Spin, Tooltip } from "antd";
import {
  Clock3,
  ExternalLink,
  Moon,
  RefreshCw,
  Settings2,
  Sun,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import { formatServerIsoDateTime } from "../../utils/formatMessageTime";
import type {
  CostMeterState,
  QuotaWindow,
} from "../../api/modules/pluginMarket";
import { useCostMeter } from "./useCostMeter";
import styles from "./index.module.less";

export function duration(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(
    2,
    "0",
  )}:${String(total % 60).padStart(2, "0")}`;
}

function QuotaRow({
  label,
  quota,
  now,
}: {
  label: string;
  quota: QuotaWindow | null;
  now: number;
}) {
  const { t } = useTranslation();
  const timezone = useServerTimezone();
  const resetPassed = Boolean(
    quota?.resets_at && Date.parse(quota.resets_at) <= now,
  );
  return (
    <div className={styles.quotaRow}>
      <div className={styles.quotaLabel}>
        <span>{label}</span>
        <strong>{quota ? `${quota.percent.toFixed(1)}%` : "—"}</strong>
      </div>
      <Progress
        aria-label={label}
        percent={Math.min(quota?.percent ?? 0, 100)}
        showInfo={false}
        size="small"
        strokeColor={quota && quota.percent >= 90 ? "#d6762c" : "#4e74c9"}
      />
      <small>
        {quota?.resets_at
          ? resetPassed
            ? t("pluginMarket.resetPending")
            : t("pluginMarket.resetsAt", {
                time: formatServerIsoDateTime(quota.resets_at, timezone),
              })
          : t("pluginMarket.resetUnknown")}
      </small>
    </div>
  );
}

export function CostMeterView({
  state,
  now,
  busy,
  onRefresh,
  onSettings,
  connectionError = false,
}: {
  state: CostMeterState;
  now: number;
  busy: boolean;
  onRefresh: () => void;
  onSettings: () => void;
  connectionError?: boolean;
}) {
  const { t } = useTranslation();
  const timezone = useServerTimezone();
  const peak = state.peak;
  const localHour = Number(
    new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Shanghai",
      hour: "2-digit",
      hourCycle: "h23",
    }).format(new Date(now)),
  );
  const expiry = state.subscription_expires_at
    ? Date.parse(state.subscription_expires_at) - now
    : null;
  return (
    <div className={styles.meter}>
      <section
        className={styles.peakCard}
        aria-label={t("pluginMarket.deepseekPeak")}
      >
        <header>
          <div className={styles.brand}>
            <span className={styles.deepseekMark}>D</span>
            <div>
              <strong>DeepSeek</strong>
              <small>{t("pluginMarket.priceClock")}</small>
            </div>
          </div>
          <span
            className={`${styles.phase} ${
              peak.in_peak ? styles.peak : styles.offpeak
            }`}
          >
            {peak.in_peak ? <Sun size={13} /> : <Moon size={13} />}
            {t(peak.in_peak ? "pluginMarket.peak" : "pluginMarket.offpeak")}
          </span>
        </header>
        <div className={styles.phaseBody}>
          <div>
            <small>
              {t(
                peak.in_peak
                  ? "pluginMarket.untilOffpeak"
                  : "pluginMarket.untilPeak",
              )}
            </small>
            <div className={styles.countdown}>
              {duration(Date.parse(peak.next_change_at) - now)}
            </div>
          </div>
          <span className={styles.priceHint}>
            {t(
              peak.in_peak
                ? "pluginMarket.standardPrice"
                : "pluginMarket.halfPrice",
            )}
          </span>
        </div>
        <div
          className={styles.schedule}
          role="img"
          aria-label={t("pluginMarket.scheduleHint")}
        >
          {Array.from({ length: 24 }, (_, hour) => (
            <Tooltip
              key={hour}
              title={`${String(hour).padStart(2, "0")}:00 ${t(
                peak.reason === "weekday" &&
                  ((hour >= 9 && hour < 12) || (hour >= 14 && hour < 18))
                  ? "pluginMarket.peak"
                  : "pluginMarket.offpeak",
              )}`}
            >
              <span
                className={`${
                  peak.reason === "weekday" &&
                  ((hour >= 9 && hour < 12) || (hour >= 14 && hour < 18))
                    ? styles.peakSegment
                    : styles.offpeakSegment
                } ${localHour === hour ? styles.currentSegment : ""}`}
              />
            </Tooltip>
          ))}
        </div>
        <div className={styles.hourLabels}>
          <span>00</span>
          <span>06</span>
          <span>12</span>
          <span>18</span>
          <span>24</span>
        </div>
        <p className={styles.scheduleNote}>
          {t(
            peak.reason === "weekend"
              ? "pluginMarket.weekendOffpeak"
              : peak.reason === "holiday"
              ? "pluginMarket.holidayOffpeak"
              : "pluginMarket.scheduleHint",
          )}
        </p>
        {!peak.calendar_supported && (
          <Alert type="info" message={t("pluginMarket.calendarUnknown")} />
        )}
        <a
          className={styles.sourceLink}
          href="https://api-docs.deepseek.com/quick_start/pricing"
          target="_blank"
          rel="noreferrer"
        >
          {t("pluginMarket.pricingSource")}
          <ExternalLink size={11} />
        </a>
      </section>
      <section className={styles.goCard} aria-label={t("pluginMarket.goQuota")}>
        <header>
          <div className={styles.brand}>
            <span className={styles.goMark}>Go</span>
            <div>
              <strong>OpenCode Go</strong>
              <small>{t("pluginMarket.usedQuota")}</small>
            </div>
          </div>
          <div className={styles.iconActions}>
            <Button
              type="text"
              size="small"
              icon={
                <RefreshCw size={14} className={busy ? styles.spinning : ""} />
              }
              disabled={busy || !state.key_configured}
              onClick={onRefresh}
              aria-label={t("pluginMarket.refresh")}
            />
            <Button
              type="text"
              size="small"
              icon={<Settings2 size={14} />}
              onClick={onSettings}
              aria-label={t("pluginMarket.configure")}
            />
          </div>
        </header>
        {connectionError && (
          <Alert
            type="warning"
            showIcon
            message={t("pluginMarket.loadFailed")}
            description={t("pluginMarket.staleData")}
            action={
              <Button size="small" onClick={onRefresh} disabled={busy}>
                {t("pluginMarket.retry")}
              </Button>
            }
          />
        )}
        {!connectionError && state.go.status === "error" && (
          <Alert
            type="warning"
            showIcon
            message={t(`pluginMarket.errors.${state.go.error_code}`, {
              defaultValue: t("pluginMarket.errors.upstream_error"),
            })}
            description={
              state.go.fetched_at ? t("pluginMarket.staleData") : undefined
            }
          />
        )}
        {!state.key_configured ? (
          <div className={styles.keyEmpty}>
            <Clock3 size={24} />
            <strong>{t("pluginMarket.connectGo")}</strong>
            <p>{t("pluginMarket.keyHint")}</p>
            <Button onClick={onSettings}>{t("pluginMarket.configure")}</Button>
          </div>
        ) : (
          <div className={styles.quotas}>
            <QuotaRow
              label={t("pluginMarket.rolling")}
              quota={state.go.rolling}
              now={now}
            />
            <QuotaRow
              label={t("pluginMarket.weekly")}
              quota={state.go.weekly}
              now={now}
            />
            <QuotaRow
              label={t("pluginMarket.monthly")}
              quota={state.go.monthly}
              now={now}
            />
          </div>
        )}
        <div className={styles.expiry}>
          <Clock3 size={14} />
          <div>
            <span>{t("pluginMarket.subscription")}</span>
            <strong>
              {expiry === null
                ? t("pluginMarket.expiryUnknown")
                : expiry <= 0
                ? t("pluginMarket.expired")
                : t("pluginMarket.daysLeft", {
                    count: Math.ceil(expiry / 86_400_000),
                  })}
            </strong>
            {state.subscription_expires_at && (
              <small>
                {formatServerIsoDateTime(
                  state.subscription_expires_at,
                  timezone,
                )}{" "}
                · {t("pluginMarket.manualExpiry")}
              </small>
            )}
          </div>
          {expiry === null && (
            <Button type="link" size="small" onClick={onSettings}>
              {t("pluginMarket.setExpiry")}
            </Button>
          )}
        </div>
        <footer>
          <span>
            {state.go.fetched_at
              ? t("pluginMarket.updatedAt", {
                  time: formatServerIsoDateTime(state.go.fetched_at, timezone),
                })
              : t("pluginMarket.notFetched")}
          </span>
          <span>{t("pluginMarket.autoRefresh")}</span>
        </footer>
      </section>
    </div>
  );
}

export default function CostMeter({ onSettings }: { onSettings: () => void }) {
  const { state, error, busy, refresh, now } = useCostMeter();
  const { t } = useTranslation();
  if (error)
    return (
      <Alert
        type="error"
        showIcon
        message={t("pluginMarket.loadFailed")}
        action={
          <Button onClick={() => void refresh()}>
            {t("pluginMarket.retry")}
          </Button>
        }
      />
    );
  if (!state)
    return (
      <div className={styles.loading}>
        <Spin />
      </div>
    );
  return (
    <CostMeterView
      state={state}
      now={now}
      busy={busy}
      onRefresh={() => void refresh(true)}
      onSettings={onSettings}
    />
  );
}
