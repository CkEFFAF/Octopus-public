/**
 * Context Insights — cross-session overview (spec 0020.2 Face B).
 * Account Token Usage stays at /token-usage; this page is session context.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Empty, Input, Segmented, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import PageShell from "../../../layouts/PageShell";
import {
  contextInsightsApi,
  type ContextInsightsDashboard,
  type ContextInsightsWindow,
} from "../../../api/modules/contextInsights";
import { apiErrorMessage } from "../../../utils/apiError";
import styles from "./index.module.less";

const number = (v: number | null | undefined) =>
  v == null
    ? "—"
    : Intl.NumberFormat(undefined, {
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(v);

const WINDOWS: ContextInsightsWindow[] = [
  "last_24h",
  "last_7d",
  "last_30d",
  "all",
];

export default function ContextInsightsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [windowAlias, setWindowAlias] =
    useState<ContextInsightsWindow>("last_30d");
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [data, setData] = useState<ContextInsightsDashboard | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(query.trim()), 250);
    return () => window.clearTimeout(id);
  }, [query]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await contextInsightsApi.dashboard({
        window: windowAlias,
        q: debounced || undefined,
        limit: 80,
      });
      setData(result);
    } catch (err) {
      setError(apiErrorMessage(err));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [windowAlias, debounced]);

  useEffect(() => {
    void load();
  }, [load]);

  const kpiCards = useMemo(() => {
    const kpi = data?.kpi;
    return [
      {
        key: "sessions",
        label: t("contextInsights.kpi.activeSessions"),
        value:
          kpi == null
            ? "—"
            : `${number(kpi.active_sessions)} / ${number(kpi.total_sessions)}`,
      },
      {
        key: "tokens",
        label: t("contextInsights.kpi.tokens"),
        value: number(kpi?.total_tokens),
        sub:
          kpi?.turns != null
            ? t("contextInsights.kpi.turnsSub", { count: kpi.turns })
            : undefined,
      },
      {
        key: "cost",
        label: t("contextInsights.kpi.cost"),
        value: "—",
        sub: t("contextInsights.kpi.costGap"),
      },
      {
        key: "cache",
        label: t("contextInsights.kpi.cache"),
        value:
          kpi?.cache_hit_percent == null ? "—" : `${kpi.cache_hit_percent}%`,
      },
      {
        key: "tools",
        label: t("contextInsights.kpi.toolCalls"),
        value: "—",
        sub: t("contextInsights.kpi.p1Gap"),
      },
      {
        key: "active",
        label: t("contextInsights.kpi.activeTime"),
        value: "—",
        sub: t("contextInsights.kpi.p1Gap"),
      },
    ];
  }, [data, t]);

  const dayChart = useMemo(() => {
    const rows = [...(data?.by_day ?? [])].reverse();
    return rows.map((b) => ({
      label: String(b.label).slice(5),
      tokens: b.total_tokens,
    }));
  }, [data]);

  return (
    <PageShell
      title={t("contextInsights.title")}
      subtitle={t("contextInsights.subtitle")}
    >
      <div className={styles.page}>
        <div className={styles.toolbar}>
          <div className={styles.balance}>
            <span>{t("contextInsights.balance")}</span>
            <strong>—</strong>
          </div>
          <Segmented
            value={windowAlias}
            onChange={(v) => setWindowAlias(v as ContextInsightsWindow)}
            options={WINDOWS.map((w) => ({
              value: w,
              label: t(`contextInsights.windows.${w}`),
            }))}
          />
        </div>
        {error && <Alert type="error" showIcon message={error} />}
        <div className={styles.kpiRow}>
          {kpiCards.map((card) => (
            <div key={card.key} className={styles.kpiCard}>
              <span>{card.label}</span>
              <strong>{card.value}</strong>
              {card.sub && <small>{card.sub}</small>}
            </div>
          ))}
        </div>
        {dayChart.length > 0 && (
          <section className={styles.chartCard}>
            <h3>{t("contextInsights.byDay")}</h3>
            <div className={styles.chartBody}>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={dayChart}>
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke="var(--fn-border-secondary, #e5e7eb)"
                  />
                  <XAxis
                    dataKey="label"
                    tick={{ fontSize: 11, fill: "var(--fn-text-tertiary)" }}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: "var(--fn-text-tertiary)" }}
                    tickFormatter={(v) => number(Number(v))}
                    width={48}
                  />
                  <RechartsTooltip
                    formatter={(v: number) => number(v)}
                    contentStyle={{
                      background: "var(--fn-bg-elevated, #fff)",
                      border: "1px solid var(--fn-border-secondary, #e5e7eb)",
                      borderRadius: 6,
                      fontSize: 12,
                    }}
                  />
                  <Bar dataKey="tokens" fill="#4f6ef7" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <p className={styles.gapNote}>{t("contextInsights.byDayNote")}</p>
          </section>
        )}
        <section className={styles.sessionsCard}>
          <div className={styles.sessionsHead}>
            <h3>
              {t("contextInsights.sessions")}
              {data ? ` · ${data.sessions.length}` : ""}
            </h3>
            <Input.Search
              allowClear
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("contextInsights.search")}
              style={{ maxWidth: 280 }}
            />
          </div>
          {loading && !data ? (
            <Spin />
          ) : data?.sessions.length ? (
            <ul className={styles.sessionList}>
              {data.sessions.map((s) => (
                <li key={`${s.agent_id}:${s.thread_id}`}>
                  <button
                    type="button"
                    onClick={() =>
                      navigate(
                        `/chat/${encodeURIComponent(s.agent_id)}/${encodeURIComponent(s.thread_id)}`,
                      )
                    }
                  >
                    <div className={styles.sessionTitle}>
                      <strong>{s.title}</strong>
                      <small>
                        {s.last_active
                          ? new Date(s.last_active * 1000).toLocaleString()
                          : "—"}
                      </small>
                    </div>
                    <div className={styles.sessionMeta}>
                      <span>
                        {t("contextInsights.kpi.tokens")}:{" "}
                        {number(s.total_tokens)}
                      </span>
                      <span>
                        {t("contextInsights.sessionTurns", {
                          count: s.turns,
                        })}
                      </span>
                      <span>
                        {t("contextInsights.kpi.cost")}: —
                      </span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <Empty description={t("contextInsights.empty")} />
          )}
        </section>
        {data?.gaps?.length ? (
          <p className={styles.gapNote}>
            {t("contextInsights.gapsNote")}: {data.gaps.join(", ")}
          </p>
        ) : null}
      </div>
    </PageShell>
  );
}
