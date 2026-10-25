import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Collapse, Empty, Segmented, Tag } from "antd";
import { useTranslation } from "react-i18next";
import { executionApi, type RunEvent } from "../../../api/modules/execution";
import styles from "./ChatDockContext.module.less";
import WorkflowReceipt from "./WorkflowReceipt";

const TECH_KEYS = new Set([
  "device_id",
  "job_id",
  "operation_id",
  "request_id",
  "run_id",
  "context_id",
  "event_id",
]);

const MAIN_KEYS = [
  "working_dir",
  "path",
  "file_path",
  "cwd",
  "duration_ms",
  "error_type",
  "before_estimated_tokens",
  "after_estimated_tokens",
  "summarized_count",
  "preserved_count",
  "command_preview",
  "command",
  "cmd",
  "argv",
] as const;

const SHORT_OUTPUT = 240;

function commandSummary(payload: Record<string, unknown>): string | null {
  if (
    typeof payload.command_preview === "string" &&
    payload.command_preview.trim()
  ) {
    return payload.command_preview.trim();
  }
  for (const key of ["command", "cmd", "argv"] as const) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) return value.trim();
    if (Array.isArray(value) && value.every((v) => typeof v === "string")) {
      const joined = value.join(" ").trim();
      if (joined) return joined;
    }
  }
  return null;
}

function pathOf(payload: Record<string, unknown>): string | null {
  for (const key of ["working_dir", "cwd", "path", "file_path"] as const) {
    const value = payload[key];
    if (typeof value === "string" && value) return value;
  }
  return null;
}

function truncateMiddle(value: string, max = 48): string {
  if (value.length <= max) return value;
  const keep = Math.floor((max - 1) / 2);
  return `${value.slice(0, keep)}…${value.slice(-keep)}`;
}

function formatDuration(ms: unknown): string | null {
  if (typeof ms !== "number" || !Number.isFinite(ms)) return null;
  return `${(ms / 1000).toFixed(1)}s`;
}

function receiptOf(
  payload: Record<string, unknown>,
): Record<string, unknown> | null {
  const receipt = payload.receipt;
  if (receipt && typeof receipt === "object" && !Array.isArray(receipt)) {
    return receipt as Record<string, unknown>;
  }
  return null;
}

function returncodeOf(payload: Record<string, unknown>): number | null {
  const receipt = receiptOf(payload);
  const raw = receipt?.returncode ?? payload.returncode;
  return typeof raw === "number" ? raw : null;
}

function outputPreview(
  payload: Record<string, unknown>,
  which: "stdout" | "stderr",
): { text: string; truncated: boolean } | null {
  const receipt = receiptOf(payload);
  const previewKey = which === "stdout" ? "stdout_preview" : "stderr_preview";
  const raw =
    (typeof receipt?.[previewKey] === "string" && receipt[previewKey]) ||
    (typeof receipt?.[which] === "string" && receipt[which]) ||
    (typeof payload[previewKey] === "string" && payload[previewKey]) ||
    (typeof payload[which] === "string" && payload[which]) ||
    null;
  if (typeof raw !== "string" || !raw) return null;
  const marked =
    receipt?.output_truncated === true || payload.output_truncated === true;
  if (raw.length <= SHORT_OUTPUT) {
    return { text: raw, truncated: Boolean(marked) };
  }
  return { text: raw.slice(0, SHORT_OUTPUT), truncated: true };
}

export default function RunReceiptBrowser({
  agentId,
  threadId,
  live,
  onRequest,
}: {
  agentId: string;
  threadId: string;
  live?: boolean;
  onRequest: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [before, setBefore] = useState<number | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [kindFilter, setKindFilter] = useState<string>("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const epoch = useRef(0);
  const busy = useRef(false);
  const paged = useRef(false);
  const load = async (older?: number) => {
    if (busy.current) return;
    busy.current = true;
    const generation = epoch.current;
    setLoading(true);
    try {
      const response = await executionApi.runs(agentId, threadId, older);
      if (generation !== epoch.current) return;
      setEvents((values) =>
        older ? [...values, ...response.events] : response.events,
      );
      setBefore(response.next_before);
      setError("");
      if (older) paged.current = true;
    } catch (failure) {
      if (generation === epoch.current)
        setError(failure instanceof Error ? failure.message : "");
    } finally {
      if (generation === epoch.current) {
        busy.current = false;
        setLoading(false);
      }
    }
  };
  useEffect(() => {
    const lifecycleEpoch = epoch;
    ++lifecycleEpoch.current;
    busy.current = false;
    paged.current = false;
    setEvents([]);
    setBefore(null);
    setStatusFilter("all");
    setKindFilter("all");
    setError("");
    void load();
    const timer = setInterval(
      () => {
        if (!document.hidden && !paged.current) void load();
      },
      live ? 5000 : 15000,
    );
    return () => {
      ++lifecycleEpoch.current;
      clearInterval(timer);
    };
    // The immutable thread target, rather than a render callback, controls loading.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId, threadId, live]);

  const statusOptions = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of events) {
      counts.set(item.status, (counts.get(item.status) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [events]);

  const kindOptions = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of events) {
      counts.set(item.kind, (counts.get(item.kind) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [events]);

  const visible = events.filter(
    (item) =>
      (statusFilter === "all" || item.status === statusFilter) &&
      (kindFilter === "all" || item.kind === kindFilter),
  );

  const hasTagFilters = statusOptions.length > 0 || kindOptions.length > 0;

  return (
    <section>
      <div className={styles.cardHead}>
        <h3>{t("chat.runInspect.title")}</h3>
        <Button
          size="small"
          loading={loading}
          onClick={() => {
            paged.current = false;
            void load();
          }}
        >
          {t("common.refresh")}
        </Button>
      </div>
      <div className={styles.tagPills}>
        {hasTagFilters ? (
          <>
            {statusOptions.length > 0 && (
              <Segmented
                size="small"
                value={statusFilter}
                aria-label={t("chat.runInspect.filterStatus")}
                onChange={(v) => setStatusFilter(String(v))}
                options={[
                  { value: "all", label: t("chat.runInspect.all") },
                  ...statusOptions.map(([status, count]) => ({
                    value: status,
                    label: `${t(`chat.runInspect.${status}`, {
                      defaultValue: status,
                    })} ${count}`,
                  })),
                ]}
              />
            )}
            {kindOptions.length > 1 && (
              <Segmented
                size="small"
                value={kindFilter}
                aria-label={t("chat.runInspect.filterKind")}
                onChange={(v) => setKindFilter(String(v))}
                options={[
                  { value: "all", label: t("chat.runInspect.allKinds") },
                  ...kindOptions.map(([kind, count]) => ({
                    value: kind,
                    label: `${t(`chat.runInspect.${kind}`, {
                      defaultValue: kind,
                    })} ${count}`,
                  })),
                ]}
              />
            )}
          </>
        ) : (
          <span className={styles.tagEmpty}>{t("chat.runInspect.noTags")}</span>
        )}
      </div>
      <p>{t("chat.runInspect.hint")}</p>
      {error && <Alert type="error" message={error} />}
      {!visible.length && !loading && (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            statusFilter === "all" && kindFilter === "all"
              ? t("chat.runInspect.empty")
              : t("chat.runInspect.noMatch")
          }
        >
          {(statusFilter !== "all" || kindFilter !== "all") && (
            <Button
              size="small"
              onClick={() => {
                setStatusFilter("all");
                setKindFilter("all");
              }}
            >
              {t("chat.runInspect.all")}
            </Button>
          )}
        </Empty>
      )}
      <div className={`${styles.sectionBody} ${styles.sectionBodyReceipts}`}>
        <Collapse
          ghost
          items={visible.map((event) => {
            const action = String(
              event.payload.action ??
                event.payload.name ??
                t(`chat.runInspect.${event.kind}`, {
                  defaultValue: event.kind,
                }),
            );
            const duration = formatDuration(event.payload.duration_ms);
            const path = pathOf(event.payload);
            const command = commandSummary(event.payload);
            const code = returncodeOf(event.payload);
            const stdout = outputPreview(event.payload, "stdout");
            const stderr = outputPreview(event.payload, "stderr");
            const receipt = receiptOf(event.payload);
            const mainFields = Object.entries(event.payload).filter(
              ([key, value]) =>
                value != null &&
                MAIN_KEYS.includes(key as (typeof MAIN_KEYS)[number]) &&
                !TECH_KEYS.has(key),
            );
            const techFields: Array<[string, string]> = [
              ["run_id", event.run_id],
              ...(event.context_id
                ? [["context_id", event.context_id] as [string, string]]
                : []),
              ...Object.entries(event.payload)
                .filter(
                  ([key, value]) =>
                    value != null &&
                    TECH_KEYS.has(key) &&
                    key !== "run_id" &&
                    key !== "context_id",
                )
                .map(
                  ([key, value]) => [key, String(value)] as [string, string],
                ),
            ];
            return {
              key: event.event_id,
              label: (
                <span className={styles.receiptSummary}>
                  <b>{action}</b>
                  <small>
                    {new Date(event.created_at * 1000).toLocaleTimeString()}
                  </small>
                  {duration && <small>{duration}</small>}
                  {command ? (
                    <small title={command} className={styles.commandHint}>
                      {truncateMiddle(command, 42)}
                    </small>
                  ) : (
                    <small className={styles.tagEmpty}>
                      {t("chat.runInspect.noCommand")}
                    </small>
                  )}
                  {code != null && (
                    <small>{t("chat.runInspect.exitCode", { code })}</small>
                  )}
                  <Tag
                    color={
                      event.status === "failed" || (code != null && code !== 0)
                        ? "error"
                        : event.status === "unknown"
                        ? "warning"
                        : code === 0
                        ? "success"
                        : undefined
                    }
                  >
                    {t(`chat.runInspect.${event.status}`, {
                      defaultValue: event.status,
                    })}
                  </Tag>
                  {path && (
                    <small title={path}>{truncateMiddle(path, 36)}</small>
                  )}
                  {stdout ? (
                    <small title={stdout.text} className={styles.commandHint}>
                      out: {truncateMiddle(stdout.text, 36)}
                      {stdout.truncated ? "…" : ""}
                    </small>
                  ) : (
                    <small className={styles.tagEmpty}>
                      {t("chat.runInspect.noOutput")}
                    </small>
                  )}
                  {stderr && (
                    <small title={stderr.text} className={styles.commandHint}>
                      err: {truncateMiddle(stderr.text, 28)}
                      {stderr.truncated ? "…" : ""}
                    </small>
                  )}
                </span>
              ),
              children: (
                <>
                  {event.kind === "job" &&
                    (
                      event.payload.observation as
                        | { status?: string }
                        | undefined
                    )?.status === "unavailable" && (
                      <Alert
                        type="warning"
                        message={t("chat.runInspect.observationUnavailable")}
                      />
                    )}
                  {typeof event.payload.request_id === "string" && (
                    <Button
                      size="small"
                      onClick={() =>
                        onRequest(event.payload.request_id as string)
                      }
                    >
                      {t("chat.runInspect.request")}
                    </Button>
                  )}
                  <dl className={styles.receiptFields}>
                    {command && (
                      <div>
                        <dt>{t("chat.runInspect.fields.command_preview")}</dt>
                        <dd>
                          <code>{command}</code>
                        </dd>
                      </div>
                    )}
                    {code != null && (
                      <div>
                        <dt>{t("chat.runInspect.fields.returncode")}</dt>
                        <dd>{code}</dd>
                      </div>
                    )}
                    {mainFields.map(([key, value]) => (
                      <div key={key}>
                        <dt>
                          {t(`chat.runInspect.fields.${key}`, {
                            defaultValue: key,
                          })}
                        </dt>
                        <dd>
                          {key === "duration_ms" && typeof value === "number"
                            ? `${(value / 1000).toFixed(1)}s`
                            : String(value)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                  {(stdout || stderr || receipt) && (
                    <details className={styles.slimDetail}>
                      <summary>{t("chat.runInspect.outputPreview")}</summary>
                      {stdout ? (
                        <pre>
                          {typeof receipt?.stdout_preview === "string"
                            ? receipt.stdout_preview
                            : stdout.text}
                        </pre>
                      ) : (
                        <p className={styles.tagEmpty}>
                          {t("chat.runInspect.noOutput")}
                        </p>
                      )}
                      {stderr && (
                        <pre>
                          {typeof receipt?.stderr_preview === "string"
                            ? receipt.stderr_preview
                            : stderr.text}
                        </pre>
                      )}
                      {receipt?.output_truncated === true && (
                        <p>{t("chat.runInspect.outputTruncated")}</p>
                      )}
                    </details>
                  )}
                  {Array.isArray(event.payload.todos) && (
                    <ul>
                      {event.payload.todos.map((todo, index) => (
                        <li key={index}>
                          {String((todo as { status?: string }).status ?? "")} ·{" "}
                          {String((todo as { content?: string }).content ?? "")}
                        </li>
                      ))}
                    </ul>
                  )}
                  {event.kind === "workflow" && (
                    <WorkflowReceipt
                      event={event}
                      agentId={agentId}
                      threadId={threadId}
                      onChanged={() => {
                        paged.current = false;
                        void load();
                      }}
                    />
                  )}
                  {Array.isArray(event.payload.source_urls) && (
                    <ul>
                      {event.payload.source_urls
                        .filter(
                          (url): url is string =>
                            typeof url === "string" && /^https?:\/\//.test(url),
                        )
                        .map((url) => (
                          <li key={url}>
                            <a href={url} target="_blank" rel="noreferrer">
                              {url}
                            </a>
                          </li>
                        ))}
                    </ul>
                  )}
                  <Collapse
                    ghost
                    items={[
                      {
                        key: "tech",
                        label: t("chat.runInspect.techFields"),
                        children: (
                          <dl className={styles.receiptFields}>
                            {techFields.map(([key, value]) => (
                              <div key={key}>
                                <dt>
                                  {t(`chat.runInspect.fields.${key}`, {
                                    defaultValue: key,
                                  })}
                                </dt>
                                <dd>
                                  <code>{value}</code>{" "}
                                  <Button
                                    size="small"
                                    type="link"
                                    onClick={() =>
                                      void navigator.clipboard?.writeText(value)
                                    }
                                  >
                                    {t("chat.contextInspect.copy")}
                                  </Button>
                                </dd>
                              </div>
                            ))}
                          </dl>
                        ),
                      },
                      {
                        key: "raw",
                        label: t("chat.runInspect.raw"),
                        children: (
                          <pre>{JSON.stringify(event.payload, null, 2)}</pre>
                        ),
                      },
                    ]}
                  />
                </>
              ),
            };
          })}
        />
      </div>
      {before && (
        <Button
          size="small"
          loading={loading}
          onClick={() => void load(before)}
        >
          {t("chat.contextInspect.older")}
        </Button>
      )}
    </section>
  );
}
