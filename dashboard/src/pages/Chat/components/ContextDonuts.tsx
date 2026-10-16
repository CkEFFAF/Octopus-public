import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import type { ContextUsageBreakdown } from "../../../api/modules/octopThreads";
import type { TrajectoryMetrics } from "../../../api/modules/trajectory";
import { CONTEXT_SEGMENT_COLORS } from "../contextInsights/segmentColors";
import styles from "./ChatDockContext.module.less";

const number = (v: number | null | undefined) =>
  v == null
    ? "—"
    : Intl.NumberFormat(undefined, {
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(v);

const TIMING_COLORS: Record<string, string> = {
  ttft: "#4f6ef7",
  thinking: "#a06ef7",
  tools: "#22c55e",
  answer: "#f59e0b",
};

type Seg = { key: string; label: string; value: number; color: string };

export function TokenDonut({
  usage,
}: {
  usage: ContextUsageBreakdown | null;
}) {
  const { t } = useTranslation();
  const data = useMemo<Seg[]>(() => {
    if (!usage?.segments?.length) return [];
    return usage.segments
      .filter((s) => s.tokens > 0)
      .map((s) => ({
        key: s.key,
        label: t(`chat.contextWindow.segments.${s.key}`, s.key),
        value: s.tokens,
        color: CONTEXT_SEGMENT_COLORS[s.key] || "#94a3b8",
      }));
  }, [usage, t]);
  const total = data.reduce((n, d) => n + d.value, 0);
  return (
    <section className={styles.donutCard} aria-label={t("chat.contextInspect.tokenDonut")}>
      <h3>{t("chat.contextInspect.tokenDonut")}</h3>
      {data.length ? (
        <div className={styles.donutRow}>
          <div className={styles.donutChart}>
            <ResponsiveContainer width="100%" height={140}>
              <PieChart>
                <Pie
                  data={data}
                  dataKey="value"
                  nameKey="label"
                  innerRadius={38}
                  outerRadius={58}
                  paddingAngle={1}
                  stroke="none"
                >
                  {data.map((d) => (
                    <Cell key={d.key} fill={d.color} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(v: number) => number(v)}
                  contentStyle={{
                    background: "var(--fn-bg-elevated, #fff)",
                    border: "1px solid var(--fn-border-secondary, #e5e7eb)",
                    borderRadius: 6,
                    fontSize: 12,
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className={styles.donutCenter}>
              <strong>{number(total || usage?.used_tokens)}</strong>
              <small>{t("chat.contextInspect.tokenTotal")}</small>
            </div>
          </div>
          <ul className={styles.donutLegend}>
            {data.map((d) => (
              <li key={d.key}>
                <i style={{ background: d.color }} />
                <span>{d.label}</span>
                <b>
                  {total ? `${((d.value / total) * 100).toFixed(1)}%` : "—"}
                </b>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className={styles.hint}>{t("chat.contextInspect.noUsage")}</p>
      )}
    </section>
  );
}

export function TimingDonut({
  metrics,
}: {
  metrics: TrajectoryMetrics | null;
}) {
  const { t } = useTranslation();
  const data = useMemo<Seg[]>(() => {
    if (!metrics) return [];
    const rows: Seg[] = [];
    if (metrics.ttft_avg_ms != null && metrics.ttft_avg_ms > 0) {
      rows.push({
        key: "ttft",
        label: t("chat.contextInspect.timingTtft"),
        value: metrics.ttft_avg_ms,
        color: TIMING_COLORS.ttft,
      });
    }
    if (metrics.llm_duration_ms != null && metrics.llm_duration_ms > 0) {
      rows.push({
        key: "thinking",
        label: t("chat.contextInspect.timingThinking"),
        value: metrics.llm_duration_ms,
        color: TIMING_COLORS.thinking,
      });
    }
    if (metrics.tool_duration_ms != null && metrics.tool_duration_ms > 0) {
      rows.push({
        key: "tools",
        label: t("chat.contextInspect.timingTools"),
        value: metrics.tool_duration_ms,
        color: TIMING_COLORS.tools,
      });
    }
    return rows;
  }, [metrics, t]);
  const totalMs = data.reduce((n, d) => n + d.value, 0);
  const activeLabel =
    totalMs > 0
      ? totalMs >= 60_000
        ? `${(totalMs / 60_000).toFixed(1)}m`
        : `${(totalMs / 1000).toFixed(1)}s`
      : "—";
  return (
    <section className={styles.donutCard} aria-label={t("chat.contextInspect.timingDonut")}>
      <h3>{t("chat.contextInspect.timingDonut")}</h3>
      {data.length ? (
        <div className={styles.donutRow}>
          <div className={styles.donutChart}>
            <ResponsiveContainer width="100%" height={140}>
              <PieChart>
                <Pie
                  data={data}
                  dataKey="value"
                  nameKey="label"
                  innerRadius={38}
                  outerRadius={58}
                  paddingAngle={1}
                  stroke="none"
                >
                  {data.map((d) => (
                    <Cell key={d.key} fill={d.color} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(v: number) => `${(v / 1000).toFixed(1)}s`}
                  contentStyle={{
                    background: "var(--fn-bg-elevated, #fff)",
                    border: "1px solid var(--fn-border-secondary, #e5e7eb)",
                    borderRadius: 6,
                    fontSize: 12,
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className={styles.donutCenter}>
              <strong>{activeLabel}</strong>
              <small>{t("chat.contextInspect.activeTime")}</small>
            </div>
          </div>
          <ul className={styles.donutLegend}>
            {data.map((d) => (
              <li key={d.key}>
                <i style={{ background: d.color }} />
                <span>{d.label}</span>
                <b>
                  {totalMs ? `${((d.value / totalMs) * 100).toFixed(1)}%` : "—"}
                </b>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className={styles.hint}>{t("chat.contextInspect.timingGap")}</p>
      )}
    </section>
  );
}
