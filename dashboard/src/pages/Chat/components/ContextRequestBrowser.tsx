import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Empty, Input, Segmented, Spin, Tag } from "antd";
import { ArrowDownAZ, ArrowUpAZ } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  executionApi,
  type RequestSnapshot,
} from "../../../api/modules/execution";
import { contextInsightsApi } from "../../../api/modules/contextInsights";
import { apiErrorMessage } from "../../../utils/apiError";
import styles from "./ChatDockContext.module.less";

const palette: Record<string, string> = {
  system: "#7063e6",
  tool_schema: "#e8a118",
  user: "#36b870",
  assistant: "#4687f4",
  tool: "#17ad9c",
  injected_context: "#a178d9",
};
const number = (n: number | null | undefined) =>
  n == null
    ? "—"
    : Intl.NumberFormat(undefined, {
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(n);

type SortKey = "time" | "tokens";
type SortDir = "asc" | "desc";

function tokenOfRequest(r: RequestSnapshot): number | null {
  const actual = r.actual_usage?.input_tokens;
  if (typeof actual === "number") return actual;
  return typeof r.estimated_input_tokens === "number"
    ? r.estimated_input_tokens
    : null;
}

function compareRequests(
  a: RequestSnapshot,
  b: RequestSnapshot,
  key: SortKey,
  dir: SortDir,
): number {
  const timeOf = (r: RequestSnapshot) => r.seq;
  if (key === "time") {
    const d = timeOf(a) - timeOf(b);
    return dir === "asc" ? d : -d;
  }
  const ta = tokenOfRequest(a);
  const tb = tokenOfRequest(b);
  if (ta == null && tb == null) {
    const d = timeOf(a) - timeOf(b);
    return dir === "asc" ? d : -d;
  }
  if (ta == null) return 1;
  if (tb == null) return -1;
  const d = ta - tb;
  return dir === "asc" ? d : -d;
}

function truncateMiddle(value: string, max = 48): string {
  if (value.length <= max) return value;
  const keep = Math.floor((max - 1) / 2);
  return `${value.slice(0, keep)}…${value.slice(-keep)}`;
}

export default function ContextRequestBrowser({
  agentId,
  threadId,
  live,
  focusRequestId,
  highlightRequestSeq,
}: {
  agentId: string;
  threadId: string;
  live?: boolean;
  focusRequestId?: string;
  highlightRequestSeq?: number | null;
}) {
  const { t } = useTranslation();
  const [requests, setRequests] = useState<RequestSnapshot[]>([]);
  const [picked, setPicked] = useState<string | null>(null);
  const [detail, setDetail] = useState<RequestSnapshot | null>(null);
  const [previous, setPrevious] = useState<RequestSnapshot | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [before, setBefore] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("time");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [kindFilter, setKindFilter] = useState<string>("all");
  const [viewGrain, setViewGrain] = useState<"step" | "turn">("step");
  const [insightsDetail, setInsightsDetail] = useState<Record<
    string,
    unknown
  > | null>(null);
  const sectionBodyRef = useRef<HTMLDivElement>(null);
  const epoch = useRef(0);
  const busy = useRef(false);
  const refresh = useCallback(
    async (older?: number) => {
      if (busy.current) return;
      busy.current = true;
      const stamp = epoch.current;
      setLoading(true);
      try {
        const result = await executionApi.requests(agentId, threadId, older);
        if (stamp !== epoch.current) return;
        setRequests((current) => {
          const merged = new Map(
            [...current, ...result.requests].map((item) => [
              item.request_id,
              item,
            ]),
          );
          return [...merged.values()];
        });
        if (older != null || before == null) setBefore(result.next_before);
        setError("");
      } catch (e) {
        if (stamp === epoch.current)
          setError(apiErrorMessage(e, t("chat.contextInspect.failed"), t));
      } finally {
        if (stamp === epoch.current) {
          busy.current = false;
          setLoading(false);
        }
      }
    },
    [agentId, threadId, t, before],
  );
  useEffect(() => {
    epoch.current += 1;
    busy.current = false;
    setRequests([]);
    setPicked(null);
    setBefore(null);
    setDetail(null);
    setPrevious(null);
    setDetailOpen(false);
    setKindFilter("all");
    setViewGrain("step");
    setInsightsDetail(null);
    setError("");
    return () => {
      epoch.current += 1;
    };
  }, [agentId, threadId]);
  useEffect(() => {
    if (focusRequestId) setPicked(focusRequestId);
  }, [focusRequestId]);
  useEffect(() => {
    if (highlightRequestSeq == null) return;
    const match = requests.find((item) => item.seq === highlightRequestSeq);
    if (match) setPicked(match.request_id);
  }, [highlightRequestSeq, requests]);
  useEffect(() => {
    void refresh();
    const timer = setInterval(
      () => {
        if (!document.hidden) void refresh();
      },
      live ? 5000 : 15000,
    );
    return () => clearInterval(timer);
  }, [refresh, live]);

  const kindOptions = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of requests) {
      for (const kind of Object.keys(item.composition ?? {})) {
        counts.set(kind, (counts.get(kind) ?? 0) + 1);
      }
    }
    return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [requests]);

  const sortedRequests = useMemo(() => {
    const filtered =
      kindFilter === "all"
        ? requests
        : requests.filter((item) =>
            Object.prototype.hasOwnProperty.call(
              item.composition ?? {},
              kindFilter,
            ),
          );
    const ordered = [...filtered].sort((a, b) =>
      compareRequests(a, b, sortKey, sortDir),
    );
    if (viewGrain === "step") return ordered;
    // Turn view: keep newest request per turn_id (fallback request_id).
    const seen = new Set<string>();
    const turns: RequestSnapshot[] = [];
    for (const item of ordered) {
      const key = String(item.turn_id || item.request_id);
      if (seen.has(key)) continue;
      seen.add(key);
      turns.push(item);
    }
    return turns;
  }, [requests, sortKey, sortDir, kindFilter, viewGrain]);

  const selectedId = picked ?? sortedRequests[0]?.request_id ?? null;
  const selectedSummary = sortedRequests.find(
    (item) => item.request_id === selectedId,
  );
  const selected =
    selectedSummary ??
    (detail && detail.request_id === selectedId
      ? {
          ...detail,
          composition: Object.keys(detail.estimated_tokens_by_kind ?? {}).length
            ? detail.estimated_tokens_by_kind!
            : detail.components.reduce<Record<string, number>>(
                (totals, component) => {
                  totals[component.kind] =
                    (totals[component.kind] ?? 0) + component.estimated_tokens;
                  return totals;
                },
                {},
              ),
        }
      : undefined);
  const previousSummary =
    selectedSummary &&
    [...requests]
      .filter((item) => item.seq < selectedSummary.seq)
      .sort((a, b) => b.seq - a.seq)[0];
  // Selecting a listed request must not eagerly pull full component detail (S3).
  // Focus / highlight of an ID missing from the page still needs a detail fetch.
  const needsFocusFetch =
    !!selectedId && !selectedSummary && selectedId === picked;
  useEffect(() => {
    setDetail(null);
    setPrevious(null);
    if (needsFocusFetch) setDetailOpen(true);
    else setDetailOpen(false);
  }, [selectedId, needsFocusFetch]);
  useEffect(() => {
    if (!selectedId || (!detailOpen && !needsFocusFetch)) return;
    let disposed = false;
    void Promise.all([
      executionApi.request(agentId, threadId, selectedId),
      previousSummary
        ? executionApi.request(agentId, threadId, previousSummary.request_id)
        : Promise.resolve(null),
      contextInsightsApi.request(agentId, threadId, selectedId, {
        includeContent: false,
      }),
    ])
      .then(([current, prev, insights]) => {
        if (!disposed) {
          setDetail(current);
          setPrevious(prev);
          setInsightsDetail(insights as unknown as Record<string, unknown>);
        }
      })
      .catch((e) => {
        if (!disposed)
          setError(apiErrorMessage(e, t("chat.contextInspect.failed"), t));
      });
    return () => {
      disposed = true;
    };
  }, [
    agentId,
    threadId,
    selectedId,
    detailOpen,
    needsFocusFetch,
    selectedSummary?.status,
    previousSummary?.request_id,
    t,
  ]);
  const olderHashes = useMemo(
    () => new Set(previous?.components.map((component) => component.sha256)),
    [previous],
  );
  const removedComponents = useMemo(() => {
    const currentHashes = new Set(detail?.components.map((c) => c.sha256));
    return (
      previous?.components.filter((c) => !currentHashes.has(c.sha256)) ?? []
    );
  }, [detail, previous]);
  useEffect(() => {
    if (highlightRequestSeq == null || !sectionBodyRef.current) return;
    const el = sectionBodyRef.current.querySelector(
      `[data-request-seq="${highlightRequestSeq}"]`,
    );
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [highlightRequestSeq, sortKey, sortDir, sortedRequests]);
  const total = selected
    ? Object.values(selected.composition).reduce((sum, value) => sum + value, 0)
    : 0;
  const delta =
    previousSummary && selectedSummary
      ? selectedSummary.estimated_input_tokens -
        previousSummary.estimated_input_tokens
      : null;
  const SortIcon = sortDir === "asc" ? ArrowUpAZ : ArrowDownAZ;
  return (
    <>
      <section>
        <div className={styles.cardHead}>
          <h3>
            {t("chat.contextInspect.requests")}
            {live ? (
              <Tag color="processing" style={{ marginLeft: 8 }}>
                {t("chat.contextInspect.live")}
              </Tag>
            ) : null}
          </h3>
          <div className={styles.sortControls}>
            <Segmented
              size="small"
              value={viewGrain}
              aria-label={t("chat.contextInspect.viewStep")}
              onChange={(v) => setViewGrain(v as "step" | "turn")}
              options={[
                {
                  value: "step",
                  label: t("chat.contextInspect.viewStep"),
                },
                {
                  value: "turn",
                  label: t("chat.contextInspect.viewTurn"),
                },
              ]}
            />
            <Segmented
              size="small"
              value={sortKey}
              aria-label={t("chat.contextInspect.sortBy")}
              onChange={(v) => setSortKey(v as SortKey)}
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
                sortDir === "asc"
                  ? t("chat.contextInspect.sortAsc")
                  : t("chat.contextInspect.sortDesc")
              }
              onClick={() => setSortDir((d) => (d === "asc" ? "desc" : "asc"))}
            />
            <Button
              size="small"
              loading={loading}
              onClick={() => void refresh()}
            >
              {t("common.refresh")}
            </Button>
          </div>
        </div>
        <div className={styles.tagPills}>
          {kindOptions.length > 0 ? (
            <Segmented
              size="small"
              value={kindFilter}
              onChange={(v) => setKindFilter(String(v))}
              options={[
                {
                  value: "all",
                  label: t("chat.contextInspect.mappedKinds.all"),
                },
                ...kindOptions.map(([kind, count]) => ({
                  value: kind,
                  label: `${t(
                    `chat.contextInspect.componentKinds.${kind}`,
                    kind,
                  )} ${count}`,
                })),
              ]}
            />
          ) : (
            <span className={styles.tagEmpty}>
              {t("chat.contextInspect.noTags")}
            </span>
          )}
        </div>
        {error && <Alert type="error" message={error} />}
        {!requests.length ? (
          loading ? (
            <Spin />
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("chat.contextInspect.noRequests")}
            />
          )
        ) : !sortedRequests.length ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={t("chat.contextInspect.noMatch")}
          >
            <Button size="small" onClick={() => setKindFilter("all")}>
              {t("chat.contextInspect.mappedKinds.all")}
            </Button>
          </Empty>
        ) : (
          <div
            ref={sectionBodyRef}
            className={`${styles.sectionBody} ${styles.sectionBodyBrowser}`}
            role="listbox"
            aria-label={t("chat.contextInspect.requests")}
          >
            <div className={styles.requestList}>
              {sortedRequests.map((item) => {
                const tokens = tokenOfRequest(item);
                const active = selectedId === item.request_id;
                return (
                  <button
                    key={item.request_id}
                    type="button"
                    role="option"
                    aria-selected={active}
                    data-request-seq={item.seq}
                    className={`${styles.requestRow} ${
                      active ? styles.requestRowActive : ""
                    }`}
                    onClick={() => setPicked(item.request_id)}
                  >
                    <span className={styles.requestRowMain}>
                      <b>
                        #{item.seq}
                        {item.model ? ` · ${item.model}` : ""}
                      </b>
                      <Tag>
                        {t(
                          `chat.contextInspect.requestStatus.${item.status}`,
                          item.status,
                        )}
                      </Tag>
                    </span>
                    <span className={styles.requestRowMeta}>
                      <small>
                        {item.actual_usage ? "" : "≈"}
                        {number(tokens)}
                      </small>
                      {item.duration_ms != null && (
                        <small>{(item.duration_ms / 1000).toFixed(1)}s</small>
                      )}
                    </span>
                  </button>
                );
              })}
            </div>
            {before != null && (
              <Button
                size="small"
                loading={loading}
                onClick={() => void refresh(before)}
              >
                {t("chat.contextInspect.older")}
              </Button>
            )}
          </div>
        )}
      </section>
      <section>
        <div className={styles.cardHead}>
          <h3>{t("chat.contextInspect.requestDetail")}</h3>
          {previousSummary && selectedSummary && (
            <Tag>
              {t("chat.contextInspect.vsPrevious", {
                delta:
                  delta == null
                    ? "—"
                    : `${delta >= 0 ? "+" : ""}${number(delta)}`,
              })}
            </Tag>
          )}
        </div>
        {!selected ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={t("chat.contextInspect.pickRequest")}
          />
        ) : (
          <div className={`${styles.sectionBody} ${styles.sectionBodyDetail}`}>
            <div className={styles.requestHeading}>
              <strong>
                #{selected.seq}
                {selected.model ? ` · ${selected.model}` : ""}
              </strong>
              <Tag>
                {t(
                  `chat.contextInspect.requestStatus.${selected.status}`,
                  selected.status,
                )}
              </Tag>
            </div>
            {insightsDetail?.effective_binding ? (
              <Alert
                type="info"
                showIcon
                message={t("chat.contextInspect.effectiveBinding")}
                description={
                  (insightsDetail.effective_binding as { execution_context?: unknown; reason_codes?: string[] })
                    .execution_context
                    ? JSON.stringify(
                        (
                          insightsDetail.effective_binding as {
                            execution_context: unknown;
                          }
                        ).execution_context,
                      )
                    : t("chat.contextInspect.missingExecutionContext")
                }
              />
            ) : null}
            {Array.isArray(insightsDetail?.turn_steps) &&
            (insightsDetail.turn_steps as unknown[]).length > 1 ? (
              <div className={styles.tagPills}>
                <span>{t("chat.contextInspect.turnSteps")}:</span>
                {(
                  insightsDetail.turn_steps as Array<{
                    request_id?: string;
                    seq?: number;
                    status?: string;
                  }>
                ).map((step) => (
                  <Button
                    key={String(step.request_id)}
                    size="small"
                    type={
                      step.request_id === selectedId ? "primary" : "default"
                    }
                    onClick={() =>
                      step.request_id && setPicked(String(step.request_id))
                    }
                  >
                    #{step.seq ?? "?"} · {step.status ?? "?"}
                  </Button>
                ))}
              </div>
            ) : null}
            <p className={styles.hint}>{t("chat.contextInspect.retainedNote")}</p>
            <details className={styles.slimDetail}>
              <summary>{t("chat.contextInspect.techFields")}</summary>
              <dl className={styles.receiptFields}>
                <div>
                  <dt>request_id</dt>
                  <dd>
                    <code>{selected.request_id}</code>{" "}
                    <Button
                      size="small"
                      type="link"
                      onClick={() =>
                        void navigator.clipboard?.writeText(selected.request_id)
                      }
                    >
                      {t("chat.contextInspect.copy")}
                    </Button>
                  </dd>
                </div>
              </dl>
            </details>
            <div className={styles.stats}>
              {[
                [
                  t("chat.contextInspect.estimatedInput"),
                  `≈${number(selected.estimated_input_tokens)}`,
                ],
                [
                  t("chat.contextInspect.input"),
                  number(selected.actual_usage?.input_tokens),
                ],
                [
                  t("chat.contextInspect.output"),
                  number(selected.actual_usage?.output_tokens),
                ],
                [
                  t("chat.contextInspect.cache"),
                  selected.actual_usage?.input_tokens
                    ? `${(
                        (selected.actual_usage.cache_read_tokens /
                          selected.actual_usage.input_tokens) *
                        100
                      ).toFixed(1)}%`
                    : "—",
                ],
                [
                  t("chat.contextInspect.modelTime"),
                  selected.duration_ms == null
                    ? "—"
                    : `${(selected.duration_ms / 1000).toFixed(1)}s`,
                ],
                [
                  t("chat.contextInspect.delta"),
                  delta == null
                    ? "—"
                    : `${delta >= 0 ? "+" : ""}${number(delta)}`,
                ],
              ].map(([label, value]) => (
                <div key={label}>
                  <span>{label}</span>
                  <strong>{value}</strong>
                </div>
              ))}
            </div>
            <div className={styles.bar}>
              {Object.entries(selected.composition ?? {}).map(
                ([kind, value]) => (
                  <i
                    key={kind}
                    style={{
                      background: palette[kind] ?? "#a178d9",
                      width: `${total ? (value / total) * 100 : 0}%`,
                    }}
                  />
                ),
              )}
            </div>
            <div className={styles.legend}>
              {Object.entries(selected.composition ?? {}).map(
                ([kind, value]) => (
                  <div key={kind}>
                    <i style={{ background: palette[kind] ?? "#a178d9" }} />
                    <span>
                      {t(`chat.contextInspect.componentKinds.${kind}`, kind)}
                    </span>
                    <b>≈{number(value)}</b>
                  </div>
                ),
              )}
            </div>
            <p>{t("chat.contextInspect.requestTruth")}</p>
            {selected.transformation && (
              <Alert
                type="info"
                message={t(
                  `chat.contextInspect.${selected.transformation.kind}`,
                )}
                description={t("chat.contextInspect.transformationDetail", {
                  before: number(
                    selected.transformation.before_estimated_tokens,
                  ),
                  after: number(selected.transformation.after_estimated_tokens),
                  beforeCount: selected.transformation.before_message_count,
                  afterCount: selected.transformation.after_message_count,
                })}
              />
            )}
            {(detail?.components_truncated || detail?.metadata_truncated) && (
              <Alert
                type="info"
                message={t("chat.contextInspect.detailsBounded", {
                  count: detail.omitted_component_count ?? 0,
                })}
              />
            )}
            <details
              className={styles.slimDetail}
              onToggle={(e) => {
                if (e.currentTarget.open) setDetailOpen(true);
              }}
            >
              <summary>{t("chat.contextInspect.expandComponents")}</summary>
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t("chat.contextInspect.search")}
                allowClear
              />
              <div className={styles.browser}>
                {detail ? (
                  detail.components
                    .filter(
                      (component) =>
                        !search ||
                        component.content
                          .toLowerCase()
                          .includes(search.toLowerCase()),
                    )
                    .map((component, index) => (
                      <details
                        className={styles.event}
                        key={`${component.kind}:${component.index}:${index}`}
                      >
                        <summary>
                          <i
                            className={styles.componentDot}
                            style={{
                              background: palette[component.kind] ?? "#a178d9",
                            }}
                          />
                          <b>
                            {t(
                              `chat.contextInspect.componentKinds.${component.kind}`,
                              component.kind,
                            )}{" "}
                            {component.index + 1}
                          </b>
                          {component.source_type === "conversation_summary" && (
                            <Tag>{t("chat.contextInspect.summarySource")}</Tag>
                          )}
                          {component.source_path && (
                            <Tag title={component.source_path}>
                              {t(
                                `chat.contextInspect.sourceTypes.${component.source_type}`,
                                {
                                  defaultValue: component.source_type,
                                },
                              )}
                            </Tag>
                          )}
                          {previous && !olderHashes.has(component.sha256) && (
                            <Tag color="green">
                              {t("chat.contextInspect.changed")}
                            </Tag>
                          )}
                          <small>≈{number(component.estimated_tokens)}</small>
                        </summary>
                        <pre>{component.content || "—"}</pre>
                        {component.source_path && (
                          <code title={component.source_path}>
                            {truncateMiddle(component.source_path)}
                          </code>
                        )}
                        {component.content_truncated && (
                          <p>{t("chat.contextInspect.truncated")}</p>
                        )}
                        {(component.source_id || component.tool_call_id) && (
                          <details className={styles.slimDetail}>
                            <summary>
                              {t("chat.contextInspect.techFields")}
                            </summary>
                            <p>
                              {component.source_id ?? component.tool_call_id}
                            </p>
                          </details>
                        )}
                      </details>
                    ))
                ) : (
                  <Spin size="small" />
                )}
              </div>
            </details>
            {removedComponents.length > 0 && (
              <details className={styles.event}>
                <summary>
                  {t("chat.contextInspect.removedComponents", {
                    count: removedComponents.length,
                  })}
                </summary>
                {removedComponents.map((component, index) => (
                  <details
                    className={styles.event}
                    key={`${component.sha256}:${index}`}
                  >
                    <summary>
                      {t(
                        `chat.contextInspect.componentKinds.${component.kind}`,
                        component.kind,
                      )}{" "}
                      · ≈{number(component.estimated_tokens)}
                    </summary>
                    <pre>{component.content || "—"}</pre>
                    {component.content_truncated && (
                      <p>{t("chat.contextInspect.truncated")}</p>
                    )}
                  </details>
                ))}
              </details>
            )}
          </div>
        )}
      </section>
    </>
  );
}
