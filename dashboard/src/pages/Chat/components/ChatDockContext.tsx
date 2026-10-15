import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Empty, Input, Segmented, Spin } from "antd";
import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  octopThreadsApi,
  type ContextUsageBreakdown,
} from "../../../api/modules/octopThreads";
import {
  trajectoryApi,
  type TrajectoryEvent,
  type TrajectoryMetrics,
} from "../../../api/modules/trajectory";
import { apiErrorMessage } from "../../../utils/apiError";
import styles from "./ChatDockContext.module.less";
import ContextRequestBrowser from "./ContextRequestBrowser";
import RunReceiptBrowser from "./RunReceiptBrowser";

const colors: Record<string, string> = {
  system_prompt: "#7164e8",
  tool_definitions: "#e9a222",
  rules: "#a376d5",
  skills: "#a376d5",
  mcp: "#db689e",
  subagent_definitions: "#6581c9",
  conversation: "#16ae9a",
};
const number = (v: number | null | undefined) =>
  v == null
    ? "—"
    : Intl.NumberFormat(undefined, {
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(v);

export default function ChatDockContext({
  agentId,
  threadId,
  live,
}: {
  agentId: string;
  threadId?: string | null;
  live?: boolean;
}) {
  const { t } = useTranslation();
  const [focusRequestId, setFocusRequestId] = useState<string>();
  const requestSection = useRef<HTMLDivElement>(null);
  const [usage, setUsage] = useState<ContextUsageBreakdown | null>(null);
  const [metrics, setMetrics] = useState<TrajectoryMetrics | null>(null);
  const [events, setEvents] = useState<TrajectoryEvent[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  const epoch = useRef(0);
  const inflight = useRef(false);
  const paged = useRef(false);
  const refresh = useCallback(
    async (older?: number) => {
      if (!threadId || inflight.current) return;
      const stamp = epoch.current;
      inflight.current = true;
      setLoading(true);
      try {
        const [window, stats, history] = await Promise.all([
          octopThreadsApi.contextUsage(agentId, threadId),
          trajectoryApi.metrics(agentId, threadId),
          trajectoryApi.history(agentId, threadId, {
            limit: 120,
            beforeSeq: older,
          }),
        ]);
        if (stamp !== epoch.current) return;
        setUsage(window);
        setMetrics(stats);
        setError("");
        setEvents((previous) => {
          const merged = new Map(
            [...previous, ...history.events].map((e) => [e.event_id, e]),
          );
          return [...merged.values()].sort((a, b) => a.seq - b.seq);
        });
        if (older != null) paged.current = true;
        setCursor((previous) =>
          older != null || !paged.current
            ? history.has_more
              ? history.next_before_seq
              : null
            : previous,
        );
      } catch (e) {
        if (stamp === epoch.current)
          setError(apiErrorMessage(e, t("chat.contextInspect.failed"), t));
      } finally {
        if (stamp === epoch.current) {
          inflight.current = false;
          setLoading(false);
        }
      }
    },
    [agentId, threadId, t],
  );
  useEffect(() => {
    epoch.current += 1;
    inflight.current = false;
    paged.current = false;
    setUsage(null);
    setMetrics(null);
    setEvents([]);
    setCursor(null);
    setPicked(null);
    setError("");
    void refresh();
    return () => {
      epoch.current += 1;
    };
  }, [refresh]);
  useEffect(() => {
    const timer = setInterval(
      () => {
        if (!document.hidden) void refresh();
      },
      live ? 5000 : 15000,
    );
    return () => clearInterval(timer);
  }, [refresh, live]);
  const points = useMemo(
    () => events.filter((e) => Number(e.payload.input_tokens) > 0),
    [events],
  );
  const maxPoint = Math.max(
    1,
    ...points.map((e) => Number(e.payload.input_tokens)),
  );
  const selected = events.find((e) => e.event_id === picked);
  const visible = events.filter(
    (e) =>
      (filter === "all" || e.kind === filter) &&
      (!selected ||
        selected.request_seq == null ||
        e.request_seq === selected.request_seq) &&
      (!search ||
        JSON.stringify(e).toLowerCase().includes(search.toLowerCase())),
  );
  const pct =
    usage && usage.max_tokens > 0
      ? Math.min(100, (usage.used_tokens / usage.max_tokens) * 100)
      : 0;
  const segmentTotal =
    usage?.segments.reduce((sum, s) => sum + Math.max(s.tokens, 0), 0) ?? 0;
  if (!threadId)
    return <Empty description={t("chat.contextInspect.noThread")} />;
  return (
    <div className={styles.panel}>
      <header>
        <div>
          <h2>{t("chat.contextInspect.title")}</h2>
          <p>{t("chat.contextInspect.subtitle")}</p>
        </div>
        <Button
          aria-label={t("common.refresh")}
          icon={<RefreshCw size={15} />}
          loading={loading}
          onClick={() => void refresh()}
        />
      </header>
      {error && <Alert type="error" message={error} />}
      <div ref={requestSection}>
        <ContextRequestBrowser
          agentId={agentId}
          threadId={threadId}
          live={live}
          focusRequestId={focusRequestId}
        />
      </div>
      <RunReceiptBrowser
        agentId={agentId}
        threadId={threadId}
        live={live}
        onRequest={(id) => {
          setFocusRequestId(id);
          requestSection.current?.scrollIntoView({
            behavior: "smooth",
            block: "start",
          });
        }}
      />
      {!usage && loading ? (
        <Spin />
      ) : (
        <>
          <div className={styles.stats}>
            {[
              [t("chat.contextInspect.turns"), number(metrics?.turns)],
              [t("chat.contextInspect.steps"), number(metrics?.steps)],
              [t("chat.contextInspect.input"), number(metrics?.input_tokens)],
              [t("chat.contextInspect.output"), number(metrics?.output_tokens)],
              [
                t("chat.contextInspect.cache"),
                metrics?.cache_hit_ratio == null
                  ? "—"
                  : `${(metrics.cache_hit_ratio * 100).toFixed(1)}%`,
              ],
              [
                t("chat.contextInspect.modelTime"),
                metrics?.llm_duration_ms == null
                  ? "—"
                  : `${(metrics.llm_duration_ms / 1000).toFixed(1)}s`,
              ],
            ].map(([label, value]) => (
              <div key={label}>
                <span>{label}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
          <section>
            <h3>{t("chat.contextInspect.current")}</h3>
            <div className={styles.occupancy}>
              <strong>
                {number(usage?.used_tokens)}{" "}
                <small>/ {number(usage?.max_tokens)}</small>
              </strong>
              <b>{pct.toFixed(1)}%</b>
            </div>
            <div
              className={styles.bar}
              role="img"
              aria-label={t("chat.contextInspect.current")}
            >
              {usage?.segments.map((s) => (
                <i
                  key={s.key}
                  style={{
                    width: `${
                      segmentTotal ? (pct * s.tokens) / segmentTotal : 0
                    }%`,
                    background: colors[s.key],
                  }}
                />
              ))}
            </div>
            <div className={styles.legend}>
              {usage?.segments.map((s) => (
                <div key={s.key}>
                  <i style={{ background: colors[s.key] }} />
                  <span>{t(`chat.contextWindow.segments.${s.key}`)}</span>
                  <b>≈{number(s.tokens)}</b>
                </div>
              ))}
            </div>
            <p>{t("chat.contextInspect.estimates")}</p>
          </section>
          <section>
            <h3>{t("chat.contextInspect.trend")}</h3>
            {points.length ? (
              <div className={styles.trend}>
                {points.map((e) => (
                  <button
                    key={e.event_id}
                    aria-label={`${t("chat.contextInspect.input")} ${number(
                      Number(e.payload.input_tokens),
                    )}`}
                    title={`${e.summary.slice(0, 80)} · ${number(
                      Number(e.payload.input_tokens),
                    )}`}
                    className={picked === e.event_id ? styles.selected : ""}
                    onClick={() =>
                      setPicked(picked === e.event_id ? null : e.event_id)
                    }
                  >
                    <i
                      style={{
                        height: `${Math.max(
                          3,
                          (Number(e.payload.input_tokens) / maxPoint) * 100,
                        )}%`,
                      }}
                    />
                    <small>{e.request_seq ?? e.seq}</small>
                  </button>
                ))}
              </div>
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t("chat.contextInspect.noUsage")}
              />
            )}
            <p>{t("chat.contextInspect.retained")}</p>
          </section>
          <section>
            <h3>{t("chat.contextInspect.browser")}</h3>
            <div className={styles.controls}>
              <Segmented
                size="small"
                value={filter}
                onChange={(v) => setFilter(String(v))}
                options={[
                  "all",
                  "system",
                  "context",
                  "user",
                  "assistant",
                  "tool",
                  "compacted",
                ].map((k) => ({
                  value: k,
                  label: t(`chat.contextInspect.kinds.${k}`),
                }))}
              />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t("chat.contextInspect.search")}
                allowClear
              />
              {picked && (
                <Button size="small" onClick={() => setPicked(null)}>
                  {t("chat.contextInspect.allSteps")}
                </Button>
              )}
            </div>
            <div className={styles.browser}>
              {visible.map((e) => (
                <ContextEvent
                  key={e.event_id}
                  event={e}
                  agentId={agentId}
                  threadId={threadId}
                />
              ))}
            </div>
            {!visible.length && (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t("chat.contextInspect.noEvents")}
              />
            )}
            {cursor != null && (
              <Button loading={loading} onClick={() => void refresh(cursor)}>
                {t("chat.contextInspect.older")}
              </Button>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function ContextEvent({
  event,
  agentId,
  threadId,
}: {
  event: TrajectoryEvent;
  agentId: string;
  threadId: string;
}) {
  const { t } = useTranslation();
  const [detail, setDetail] = useState<TrajectoryEvent | null>(null);
  const [error, setError] = useState(false);
  return (
    <details
      className={styles.event}
      onToggle={async (e) => {
        if (!e.currentTarget.open || detail) return;
        try {
          setDetail(
            await trajectoryApi.event(agentId, threadId, event.event_id),
          );
          setError(false);
        } catch {
          setError(true);
        }
      }}
    >
      <summary>
        <span>{t(`chat.contextInspect.kinds.${event.kind}`, event.kind)}</span>
        <b>{event.summary || (event.payload.name as string) || "—"}</b>
        <small>#{event.request_seq ?? event.seq}</small>
      </summary>
      {error ? (
        <Alert type="error" message={t("chat.contextInspect.failed")} />
      ) : detail ? (
        <pre>{JSON.stringify(detail.payload, null, 2)}</pre>
      ) : (
        <Spin size="small" />
      )}
    </details>
  );
}
