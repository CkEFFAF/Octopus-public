import { useEffect, useRef, useState } from "react";
import { Alert, Button, Collapse, Empty, Select, Tag } from "antd";
import { useTranslation } from "react-i18next";
import { executionApi, type RunEvent } from "../../../api/modules/execution";
import styles from "./ChatDockContext.module.less";
import WorkflowReceipt from "./WorkflowReceipt";

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
  const [run, setRun] = useState<string>();
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
    ++epoch.current;
    busy.current = false;
    paged.current = false;
    setEvents([]);
    setBefore(null);
    setRun(undefined);
    setError("");
    void load();
    const timer = setInterval(
      () => {
        if (!document.hidden && !paged.current) void load();
      },
      live ? 5000 : 15000,
    );
    return () => {
      ++epoch.current;
      clearInterval(timer);
    };
    // The immutable thread target, rather than a render callback, controls loading.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId, threadId, live]);
  const runs = [...new Set(events.map((item) => item.run_id))];
  const visible = events.filter((item) => !run || item.run_id === run);
  return (
    <section>
      <div className={styles.requestHeading}>
        <h3>{t("chat.runInspect.title")}</h3>
        <Select
          aria-label={t("chat.runInspect.filter")}
          value={run}
          allowClear
          placeholder={t("chat.runInspect.all")}
          onChange={setRun}
          options={runs.map((id) => ({ value: id, label: id }))}
          style={{ minWidth: 160, maxWidth: 240 }}
        />
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
      <p>{t("chat.runInspect.hint")}</p>
      {error && <Alert type="error" message={error} />}
      {!visible.length && !loading && (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("chat.runInspect.empty")}
        />
      )}
      <Collapse
        ghost
        items={visible.map((event) => ({
          key: event.event_id,
          label: (
            <span>
              <Tag
                color={
                  event.status === "failed"
                    ? "error"
                    : event.status === "unknown"
                    ? "warning"
                    : undefined
                }
              >
                {t(`chat.runInspect.${event.status}`, {
                  defaultValue: event.status,
                })}
              </Tag>{" "}
              {String(
                event.payload.action ??
                  event.payload.name ??
                  t(`chat.runInspect.${event.kind}`, {
                    defaultValue: event.kind,
                  }),
              )}{" "}
              · {new Date(event.created_at * 1000).toLocaleTimeString()}
            </span>
          ),
          children: (
            <>
              <small>
                Run {event.run_id}
                {event.context_id ? ` · ${event.context_id}` : ""}
              </small>
              {event.kind === "job" &&
                (event.payload.observation as { status?: string } | undefined)
                  ?.status === "unavailable" && (
                  <Alert
                    type="warning"
                    message={t("chat.runInspect.observationUnavailable")}
                  />
                )}
              {typeof event.payload.request_id === "string" && (
                <Button
                  size="small"
                  onClick={() => onRequest(event.payload.request_id as string)}
                >
                  {t("chat.runInspect.request")}
                </Button>
              )}
              <dl className={styles.receiptFields}>
                {Object.entries(event.payload)
                  .filter(
                    ([key, value]) =>
                      value != null &&
                      [
                        "device_id",
                        "working_dir",
                        "path",
                        "file_path",
                        "cwd",
                        "job_id",
                        "operation_id",
                        "duration_ms",
                        "error_type",
                        "before_estimated_tokens",
                        "after_estimated_tokens",
                        "summarized_count",
                        "preserved_count",
                      ].includes(key),
                  )
                  .map(([key, value]) => (
                    <div key={key}>
                      <dt>
                        {t(`chat.runInspect.fields.${key}`, {
                          defaultValue: key,
                        })}
                      </dt>
                      <dd>{String(value)}</dd>
                    </div>
                  ))}
              </dl>
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
        }))}
      />
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
