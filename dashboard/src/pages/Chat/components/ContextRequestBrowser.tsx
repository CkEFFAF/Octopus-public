import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Empty, Input, Select, Spin, Tag } from "antd";
import { useTranslation } from "react-i18next";
import {
  executionApi,
  type RequestSnapshot,
} from "../../../api/modules/execution";
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
  const [before, setBefore] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
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
          return [...merged.values()].sort((a, b) => b.seq - a.seq);
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
  const selectedId = picked ?? requests[0]?.request_id;
  const selectedSummary = requests.find(
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
    selectedSummary && requests.find((item) => item.seq < selectedSummary.seq);
  useEffect(() => {
    if (!selectedId) return;
    let disposed = false;
    setDetail(null);
    setPrevious(null);
    void Promise.all([
      executionApi.request(agentId, threadId, selectedId),
      previousSummary
        ? executionApi.request(agentId, threadId, previousSummary.request_id)
        : Promise.resolve(null),
    ])
      .then(([current, prev]) => {
        if (!disposed) {
          setDetail(current);
          setPrevious(prev);
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
  const points = [...requests].reverse();
  const max = Math.max(
    1,
    ...points.map(
      (item) => item.actual_usage?.input_tokens ?? item.estimated_input_tokens,
    ),
  );
  const total = selected
    ? Object.values(selected.composition).reduce((sum, value) => sum + value, 0)
    : 0;
  const delta =
    previous && selected
      ? selected.estimated_input_tokens - previous.estimated_input_tokens
      : null;
  return (
    <>
      <section>
        <div className={styles.requestHeading}>
          <h3>
            {t("chat.contextInspect.requests")}
            {live ? (
              <Tag color="processing" style={{ marginLeft: 8 }}>
                {t("chat.contextInspect.live")}
              </Tag>
            ) : null}
          </h3>
          <Button size="small" loading={loading} onClick={() => void refresh()}>
            {t("common.refresh")}
          </Button>
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
        ) : (
          <>
            <div className={styles.trend}>
              {points.map((item) => (
                <button
                  key={item.request_id}
                  className={
                    selected?.request_id === item.request_id
                      ? styles.selected
                      : ""
                  }
                  onClick={() => setPicked(item.request_id)}
                  aria-label={`${t("chat.contextInspect.request")} ${item.seq}`}
                  title={`${item.model ?? "—"} · ${
                    item.actual_usage ? "" : "≈"
                  }${number(
                    item.actual_usage?.input_tokens ??
                      item.estimated_input_tokens,
                  )}`}
                >
                  <i
                    style={{
                      height: `${Math.max(
                        3,
                        ((item.actual_usage?.input_tokens ??
                          item.estimated_input_tokens) /
                          max) *
                          100,
                      )}%`,
                    }}
                  />
                  <small>{item.seq}</small>
                </button>
              ))}
            </div>
            <div className={styles.requestHeading}>
              <Select
                size="small"
                value={selectedId}
                onChange={setPicked}
                options={[
                  ...requests,
                  ...(selected && !selectedSummary ? [selected] : []),
                ].map((item) => ({
                  value: item.request_id,
                  label: `#${item.seq} · ${item.model ?? "—"}`,
                }))}
              />
              <Tag>
                {t(
                  `chat.contextInspect.requestStatus.${selected?.status}`,
                  selected?.status ?? "",
                )}
              </Tag>
            </div>
            <div className={styles.stats}>
              {[
                [
                  t("chat.contextInspect.estimatedInput"),
                  `≈${number(selected?.estimated_input_tokens)}`,
                ],
                [
                  t("chat.contextInspect.input"),
                  number(selected?.actual_usage?.input_tokens),
                ],
                [
                  t("chat.contextInspect.output"),
                  number(selected?.actual_usage?.output_tokens),
                ],
                [
                  t("chat.contextInspect.cache"),
                  selected?.actual_usage?.input_tokens
                    ? `${(
                        (selected.actual_usage.cache_read_tokens /
                          selected.actual_usage.input_tokens) *
                        100
                      ).toFixed(1)}%`
                    : "—",
                ],
                [
                  t("chat.contextInspect.modelTime"),
                  selected?.duration_ms == null
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
              {Object.entries(selected?.composition ?? {}).map(
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
              {Object.entries(selected?.composition ?? {}).map(
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
            {selected?.transformation && (
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
            {before != null && (
              <Button
                size="small"
                loading={loading}
                onClick={() => void refresh(before)}
              >
                {t("chat.contextInspect.older")}
              </Button>
            )}
          </>
        )}
      </section>
      {selected && (
        <section>
          <div className={styles.requestHeading}>
            <h3>{t("chat.contextInspect.finalRequest")}</h3>
            {previous && (
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
          {(detail?.components_truncated || detail?.metadata_truncated) && (
            <Alert
              type="info"
              message={t("chat.contextInspect.detailsBounded", {
                count: detail.omitted_component_count ?? 0,
              })}
            />
          )}
          <details className={styles.slimDetail}>
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
                      <code>{component.source_path}</code>
                    )}
                    {component.content_truncated && (
                      <p>{t("chat.contextInspect.truncated")}</p>
                    )}
                    {(component.source_id || component.tool_call_id) && (
                      <p>{component.source_id ?? component.tool_call_id}</p>
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
        </section>
      )}
    </>
  );
}
