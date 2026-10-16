import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Empty, Input, Segmented, Spin, Tag } from "antd";
import { ArrowDownAZ, ArrowUpAZ, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  type ContextUsageBreakdown,
} from "../../../api/modules/octopThreads";
import {
  contextInsightsApi,
  type CoverageBlock,
  type InsightsStats,
} from "../../../api/modules/contextInsights";
import {
  trajectoryApi,
  type TrajectoryEvent,
} from "../../../api/modules/trajectory";
import { apiErrorMessage } from "../../../utils/apiError";
import {
  isCompactMark,
  mapTrajectoryKind,
  MAPPED_KIND_FILTERS,
  type MappedContextKind,
} from "../contextInsights/mapEventKind";
import { CONTEXT_SEGMENT_COLORS } from "../contextInsights/segmentColors";
import styles from "./ChatDockContext.module.less";
import ContextRequestBrowser from "./ContextRequestBrowser";
import RunReceiptBrowser from "./RunReceiptBrowser";

const number = (v: number | null | undefined) =>
  v == null
    ? "—"
    : Intl.NumberFormat(undefined, {
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(v);

type TrendMetric = "total" | "delta";
type TrendGrain = "step" | "turn";
type SortKey = "time" | "tokens";
type SortDir = "asc" | "desc";

function tokenOfEvent(e: TrajectoryEvent): number | null {
  const delta = e.payload.token_delta;
  if (typeof delta === "number") return delta;
  const tokens = e.payload.input_tokens;
  if (typeof tokens === "number") return tokens;
  return null;
}

function compareEvents(
  a: TrajectoryEvent,
  b: TrajectoryEvent,
  key: SortKey,
  dir: SortDir,
): number {
  const timeOf = (e: TrajectoryEvent) => e.seq;
  if (key === "time") {
    const d = timeOf(a) - timeOf(b);
    return dir === "asc" ? d : -d;
  }
  const ta = tokenOfEvent(a);
  const tb = tokenOfEvent(b);
  if (ta == null && tb == null) {
    const d = timeOf(a) - timeOf(b);
    return dir === "asc" ? d : -d;
  }
  if (ta == null) return 1;
  if (tb == null) return -1;
  const d = ta - tb;
  return dir === "asc" ? d : -d;
}

function formatDuration(ms: unknown): string | null {
  if (typeof ms !== "number" || !Number.isFinite(ms)) return null;
  return `${(ms / 1000).toFixed(1)}s`;
}

function pathOf(payload: Record<string, unknown>): string | null {
  for (const key of ["working_dir", "cwd", "path", "file_path"] as const) {
    const value = payload[key];
    if (typeof value === "string" && value) return value;
  }
  return null;
}

function truncateMiddle(value: string, max = 40): string {
  if (value.length <= max) return value;
  const keep = Math.floor((max - 1) / 2);
  return `${value.slice(0, keep)}…${value.slice(-keep)}`;
}

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
  const eventsBodyRef = useRef<HTMLDivElement>(null);
  const [usage, setUsage] = useState<ContextUsageBreakdown | null>(null);
  const [metrics, setMetrics] = useState<InsightsStats | null>(null);
  const [coverage, setCoverage] = useState<CoverageBlock | null>(null);
  const [insightsAsOf, setInsightsAsOf] = useState<string | null>(null);
  const [events, setEvents] = useState<TrajectoryEvent[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<MappedContextKind | "all">("all");
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  const [trendMetric, setTrendMetric] = useState<TrendMetric>("total");
  const [trendGrain, setTrendGrain] = useState<TrendGrain>("step");
  const [eventSortKey, setEventSortKey] = useState<SortKey>("time");
  const [eventSortDir, setEventSortDir] = useState<SortDir>("desc");
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
        const [inspected, history] = await Promise.all([
          contextInsightsApi.inspect(agentId, threadId, {
            include: ["stats", "breakdown", "trend", "execution", "meters"],
            trendLimit: 40,
          }),
          trajectoryApi.history(agentId, threadId, {
            limit: 120,
            beforeSeq: older,
          }),
        ]);
        if (stamp !== epoch.current) return;
        const window: ContextUsageBreakdown | null = inspected.breakdown
          ? {
              max_tokens: inspected.breakdown.max_tokens,
              used_tokens: inspected.breakdown.used_tokens,
              segments: inspected.breakdown.segments as ContextUsageBreakdown["segments"],
            }
          : null;
        setUsage(window);
        setMetrics(inspected.stats ?? null);
        setCoverage(inspected.coverage ?? null);
        setInsightsAsOf(inspected.as_of ?? null);
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
    setCoverage(null);
    setInsightsAsOf(null);
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

  const trendPoints = useMemo(() => {
    const withTokens = events.filter((e) => Number(e.payload.input_tokens) > 0);
    if (trendGrain === "step") {
      return withTokens.map((e, index, all) => {
        const tokens = Number(e.payload.input_tokens);
        const prev =
          index > 0 ? Number(all[index - 1].payload.input_tokens) : null;
        return {
          key: e.event_id,
          event: e,
          total: tokens,
          delta: prev == null ? null : tokens - prev,
          label: e.request_seq ?? e.seq,
          scissors: isCompactMark(e.kind, e.payload),
        };
      });
    }
    const byTurn = new Map<string, TrajectoryEvent>();
    for (const e of withTokens) {
      const turnKey = e.turn_id || `seq:${e.request_seq ?? e.seq}`;
      byTurn.set(turnKey, e);
    }
    const ordered = [...byTurn.values()].sort((a, b) => a.seq - b.seq);
    return ordered.map((e, index, all) => {
      const tokens = Number(e.payload.input_tokens);
      const prev =
        index > 0 ? Number(all[index - 1].payload.input_tokens) : null;
      return {
        key: e.event_id,
        event: e,
        total: tokens,
        delta: prev == null ? null : tokens - prev,
        label: e.request_seq ?? e.seq,
        scissors: isCompactMark(e.kind, e.payload),
      };
    });
  }, [events, trendGrain]);

  const maxPoint = Math.max(
    1,
    ...trendPoints.map((p) =>
      trendMetric === "total" ? p.total : Math.abs(p.delta ?? 0),
    ),
  );
  const selected = events.find((e) => e.event_id === picked);
  const visible = useMemo(() => {
    const filtered = events.filter((e) => {
      const mapped = mapTrajectoryKind(e.kind, e.payload);
      if (filter !== "all" && mapped !== filter && e.kind !== filter)
        return false;
      if (
        selected &&
        selected.request_seq != null &&
        e.request_seq !== selected.request_seq
      )
        return false;
      if (
        search &&
        !JSON.stringify(e).toLowerCase().includes(search.toLowerCase())
      )
        return false;
      return true;
    });
    return [...filtered].sort((a, b) =>
      compareEvents(a, b, eventSortKey, eventSortDir),
    );
  }, [events, filter, search, selected, eventSortKey, eventSortDir]);

  useEffect(() => {
    if (!picked || !eventsBodyRef.current) return;
    const el = eventsBodyRef.current.querySelector(
      `[data-event-id="${picked}"]`,
    );
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [picked, eventSortKey, eventSortDir, visible]);

  const pct =
    usage && usage.max_tokens > 0
      ? Math.min(100, (usage.used_tokens / usage.max_tokens) * 100)
      : 0;
  const segmentTotal =
    usage?.segments.reduce((sum, s) => sum + Math.max(s.tokens, 0), 0) ?? 0;

  const pickTrend = (event: TrajectoryEvent) => {
    setPicked(picked === event.event_id ? null : event.event_id);
  };

  const SortIcon = eventSortDir === "asc" ? ArrowUpAZ : ArrowDownAZ;

  if (!threadId)
    return <Empty description={t("chat.contextInspect.noThread")} />;
  return (
    <div className={styles.panel}>
      <header>
        <div>
          <h2>{t("chat.contextInspect.title")}</h2>
          <p>{t("chat.contextInspect.subtitle")}</p>
          {coverage ? (
            <p className={styles.hint}>
              {t("chat.contextInspect.coverage")}: {coverage.coverage}
              {coverage.reason_codes?.length
                ? ` · ${coverage.reason_codes.join(", ")}`
                : ""}
              {insightsAsOf ? ` · ${insightsAsOf}` : ""}
            </p>
          ) : null}
        </div>
        <Button
          aria-label={t("common.refresh")}
          icon={<RefreshCw size={15} />}
          loading={loading}
          onClick={() => void refresh()}
        />
      </header>
      {error && <Alert type="error" message={error} />}
      {!usage && loading ? (
        <Spin />
      ) : (
        <>
          <div className={styles.summaryGrid}>
            <div className={styles.stats}>
              {[
                [
                  t("chat.contextInspect.humanTurns"),
                  number(metrics?.human_turns ?? metrics?.turns),
                ],
                [
                  t("chat.contextInspect.modelRequests"),
                  number(metrics?.model_requests),
                ],
                [
                  t("chat.contextInspect.trajectoryEvents"),
                  number(metrics?.trajectory_events ?? metrics?.steps),
                ],
                [t("chat.contextInspect.input"), number(metrics?.input_tokens)],
                [
                  t("chat.contextInspect.output"),
                  number(metrics?.output_tokens),
                ],
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
                      background: CONTEXT_SEGMENT_COLORS[s.key],
                    }}
                  />
                ))}
              </div>
              <div className={styles.legend}>
                {usage?.segments.map((s) => (
                  <div key={s.key}>
                    <i style={{ background: CONTEXT_SEGMENT_COLORS[s.key] }} />
                    <span>{t(`chat.contextWindow.segments.${s.key}`)}</span>
                    <b>≈{number(s.tokens)}</b>
                  </div>
                ))}
              </div>
              <p>{t("chat.contextInspect.estimates")}</p>
              <p className={styles.hint}>
                {t("chat.contextInspect.meterSame")}
              </p>
            </section>
          </div>
          <section>
            <div className={styles.requestHeading}>
              <h3>{t("chat.contextInspect.trend")}</h3>
              <div className={styles.trendControls}>
                <Segmented
                  size="small"
                  value={trendMetric}
                  onChange={(v) => setTrendMetric(v as TrendMetric)}
                  options={[
                    {
                      value: "total",
                      label: t("chat.contextInspect.trendTotal"),
                    },
                    {
                      value: "delta",
                      label: t("chat.contextInspect.trendDelta"),
                    },
                  ]}
                />
                <Segmented
                  size="small"
                  value={trendGrain}
                  onChange={(v) => setTrendGrain(v as TrendGrain)}
                  options={[
                    {
                      value: "step",
                      label: t("chat.contextInspect.trendStep"),
                    },
                    {
                      value: "turn",
                      label: t("chat.contextInspect.trendTurn"),
                    },
                  ]}
                />
              </div>
            </div>
            {trendPoints.length ? (
              <div className={styles.trend}>
                {trendPoints.map((point) => {
                  const value =
                    trendMetric === "total"
                      ? point.total
                      : Math.abs(point.delta ?? 0);
                  const height = Math.max(3, (value / maxPoint) * 100);
                  return (
                    <button
                      key={point.key}
                      aria-label={`${t("chat.contextInspect.input")} ${number(
                        trendMetric === "total"
                          ? point.total
                          : point.delta ?? 0,
                      )}`}
                      title={`${point.event.summary.slice(0, 80)} · ${number(
                        trendMetric === "total"
                          ? point.total
                          : point.delta ?? 0,
                      )}${point.scissors ? " ✂" : ""}`}
                      className={
                        picked === point.event.event_id ? styles.selected : ""
                      }
                      onClick={() => pickTrend(point.event)}
                    >
                      {point.scissors && (
                        <em className={styles.scissors} aria-hidden>
                          ✂
                        </em>
                      )}
                      <i
                        style={{
                          height: `${height}%`,
                          background:
                            trendMetric === "delta" && (point.delta ?? 0) < 0
                              ? "#db689e"
                              : undefined,
                        }}
                      />
                      <small>{point.label}</small>
                    </button>
                  );
                })}
              </div>
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t("chat.contextInspect.noUsage")}
              />
            )}
            <p>{t("chat.contextInspect.retained")}</p>
          </section>
        </>
      )}
      <div ref={requestSection}>
        <ContextRequestBrowser
          agentId={agentId}
          threadId={threadId}
          live={live}
          focusRequestId={focusRequestId}
          highlightRequestSeq={selected?.request_seq ?? null}
        />
      </div>
      <section>
        <div className={styles.cardHead}>
          <h3>{t("chat.contextInspect.events")}</h3>
          <div className={styles.sortControls}>
            <Segmented
              size="small"
              value={eventSortKey}
              aria-label={t("chat.contextInspect.sortBy")}
              onChange={(v) => setEventSortKey(v as SortKey)}
              options={[
                {
                  value: "time",
                  label: t("chat.contextInspect.sortTime"),
                },
                {
                  value: "tokens",
                  label: t("chat.contextInspect.sortTokens"),
                },
              ]}
            />
            <Button
              size="small"
              icon={<SortIcon size={14} />}
              aria-label={
                eventSortDir === "asc"
                  ? t("chat.contextInspect.sortAsc")
                  : t("chat.contextInspect.sortDesc")
              }
              onClick={() =>
                setEventSortDir((d) => (d === "asc" ? "desc" : "asc"))
              }
            />
          </div>
        </div>
        <div className={styles.tagPills}>
          <Segmented
            size="small"
            value={filter}
            onChange={(v) => setFilter(String(v) as MappedContextKind | "all")}
            options={MAPPED_KIND_FILTERS.map((k) => ({
              value: k,
              label: t(`chat.contextInspect.mappedKinds.${k}`),
            }))}
          />
        </div>
        <div className={styles.controls}>
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
        <div
          ref={eventsBodyRef}
          className={`${styles.sectionBody} ${styles.sectionBodyEvents}`}
        >
          <div className={styles.browser}>
            {visible.map((e) => (
              <ContextEvent
                key={e.event_id}
                event={e}
                agentId={agentId}
                threadId={threadId}
                active={picked === e.event_id}
                onPick={() =>
                  setPicked(picked === e.event_id ? null : e.event_id)
                }
              />
            ))}
          </div>
        </div>
        {!visible.length && (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              filter === "all"
                ? t("chat.contextInspect.noEvents")
                : t("chat.contextInspect.noMatch")
            }
          >
            {filter !== "all" && (
              <Button size="small" onClick={() => setFilter("all")}>
                {t("chat.contextInspect.mappedKinds.all")}
              </Button>
            )}
          </Empty>
        )}
        {cursor != null && (
          <Button loading={loading} onClick={() => void refresh(cursor)}>
            {t("chat.contextInspect.older")}
          </Button>
        )}
      </section>
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
    </div>
  );
}

function ContextEvent({
  event,
  agentId,
  threadId,
  active,
  onPick,
}: {
  event: TrajectoryEvent;
  agentId: string;
  threadId: string;
  active?: boolean;
  onPick?: () => void;
}) {
  const { t } = useTranslation();
  const [detail, setDetail] = useState<TrajectoryEvent | null>(null);
  const [error, setError] = useState(false);
  const mapped = mapTrajectoryKind(event.kind, event.payload);
  const duration = formatDuration(event.payload.duration_ms);
  const path = pathOf(event.payload);
  const action =
    event.summary ||
    (typeof event.payload.action === "string" ? event.payload.action : null) ||
    (typeof event.payload.name === "string" ? event.payload.name : null) ||
    "—";
  const tokens = tokenOfEvent(event);
  const techEntries: Array<[string, string]> = [
    ["event_id", event.event_id],
    ...(typeof event.payload.request_id === "string"
      ? [["request_id", event.payload.request_id] as [string, string]]
      : []),
    ...(typeof event.payload.run_id === "string"
      ? [["run_id", event.payload.run_id] as [string, string]]
      : []),
    ...(typeof event.payload.device_id === "string"
      ? [["device_id", event.payload.device_id] as [string, string]]
      : []),
  ];
  return (
    <details
      data-event-id={event.event_id}
      className={`${styles.event} ${active ? styles.eventActive : ""}`}
      onToggle={async (e) => {
        if (e.currentTarget.open) onPick?.();
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
        <Tag>{t(`chat.contextInspect.mappedKinds.${mapped}`, mapped)}</Tag>
        <b>{action}</b>
        {isCompactMark(event.kind, event.payload) && (
          <span className={styles.scissorsInline} aria-hidden>
            ✂
          </span>
        )}
        <small>#{event.request_seq ?? event.seq}</small>
        {duration && <small>{duration}</small>}
        {tokens != null && <small>{number(tokens)}</small>}
        {path && (
          <small title={path} className={styles.pathHint}>
            {truncateMiddle(path)}
          </small>
        )}
      </summary>
      {error ? (
        <Alert type="error" message={t("chat.contextInspect.failed")} />
      ) : detail ? (
        <>
          <details className={styles.slimDetail} open={false}>
            <summary>{t("chat.contextInspect.techFields")}</summary>
            <dl className={styles.receiptFields}>
              {techEntries.map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>
                    <code>{value}</code>{" "}
                    <Button
                      size="small"
                      type="link"
                      onClick={() => void navigator.clipboard?.writeText(value)}
                    >
                      {t("chat.contextInspect.copy")}
                    </Button>
                  </dd>
                </div>
              ))}
            </dl>
          </details>
          <pre>{JSON.stringify(detail.payload, null, 2)}</pre>
        </>
      ) : (
        <Spin size="small" />
      )}
    </details>
  );
}
