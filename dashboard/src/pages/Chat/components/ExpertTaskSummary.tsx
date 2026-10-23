import { useEffect, useRef, useState } from "react";
import { Alert, Button, Empty, Modal, Tag, Segmented, Pagination } from "antd";
import { Terminal, MessageSquare, ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useSidebarActivity } from "../hooks/useSidebarActivity";
import {
  activityApi,
  type ActivityNode,
  type ActivitySnapshot,
  type BackgroundJobPage,
} from "../../../api/modules/activity";
import { ActivityStatus, NodeDetail } from "./TaskActivity";
import { apiErrorMessage } from "../../../utils/apiError";
import { localizedPreview, previewText } from "../utils/sessionPreview";
import { useServerTimezone } from "../../../hooks/useServerTimezone";
import { formatMessageTime } from "../../../utils/formatMessageTime";
import styles from "./ExpertTaskSummary.module.less";

export default function ExpertTaskSummary({
  agentId,
  threadId,
}: {
  agentId: string;
  threadId?: string;
}) {
  const { t, i18n } = useTranslation();
  const translate = useRef(t);
  translate.current = t;
  const timezone = useServerTimezone();
  const status = useSidebarActivity()[agentId];
  const [detail, setDetail] = useState<{
    thread: string;
    value: ActivitySnapshot;
  } | null>(null);
  const [selected, setSelected] = useState("");
  const [limit, setLimit] = useState(8);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [lifecycle, setLifecycle] = useState("active");
  const [recordState, setRecordState] = useState("active");
  const [offset, setOffset] = useState(0);
  const [jobPage, setJobPage] = useState<{
    key: string;
    value: BackgroundJobPage;
  } | null>(null);
  const pageKey = `${agentId}:${threadId ?? ""}:${lifecycle}:${offset}`;
  const page = jobPage?.key === pageKey ? jobPage.value : null;
  useEffect(() => {
    let alive = true;
    let inFlight = false;
    async function refresh() {
      if (inFlight) return;
      inFlight = true;
      try {
        const value = await activityApi.backgroundJobs(
          agentId,
          lifecycle,
          threadId,
          offset,
        );
        if (alive) {
          if (offset > 0 && offset >= value.total) {
            setOffset(Math.floor(Math.max(0, value.total - 1) / 20) * 20);
            return;
          }
          setJobPage({ key: pageKey, value });
          setError("");
        }
      } catch (e) {
        if (alive)
          setError(
            apiErrorMessage(
              e,
              translate.current("common.error"),
              translate.current,
            ),
          );
      } finally {
        inFlight = false;
      }
    }
    void refresh();
    const timer = window.setInterval(() => {
      if (!document.hidden) void refresh();
    }, 5000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [agentId, threadId, lifecycle, offset, pageKey]);
  const epoch = useRef(0);
  useEffect(
    () => () => {
      ++epoch.current;
    },
    [agentId, threadId],
  );
  const threads = new Map(
    (status?.working_threads ?? [])
      .filter(
        (r) =>
          lifecycle === "active" && (!threadId || r.thread_id === threadId),
      )
      .map((r) => [r.thread_id, r]),
  );
  const jobs =
    page?.items ??
    (lifecycle === "active"
      ? (status?.background_tasks ?? []).filter(
          (r) => !r.stale && (!threadId || r.thread_id === threadId),
        )
      : []);
  if (page) {
    for (const [id] of threads) {
      if (
        status?.background_tasks?.some((job) => job.thread_id === id) &&
        !jobs.some((job) => job.thread_id === id)
      )
        threads.delete(id);
    }
  }
  const ids = new Set([...threads.keys(), ...jobs.map((job) => job.thread_id)]);
  const nodes = [...(detail?.value.nodes ?? [])].sort(
    (a, b) =>
      Number(b.status === "running") - Number(a.status === "running") ||
      b.updated_at - a.updated_at,
  );
  const chosen = nodes.find((node) => node.id === selected);
  const group = (node: ActivityNode) =>
    node.observed_status === "stale"
      ? "inactive"
      : ["running", "waiting", "queued", "pending", "accepted"].includes(
          node.status,
        )
      ? "active"
      : node.status === "completed"
      ? "completed"
      : node.status === "failed"
      ? "failed"
      : "inactive";
  const visibleNodes = nodes.filter(
    (node) => recordState === "all" || group(node) === recordState,
  );
  const nodeName = (node: ActivityNode, index: number) => {
    if (["command.run", "execute"].includes(node.name))
      return t("sessionPreview.toolCommand");
    if (node.name === "schedule_self_check")
      return t("sessionPreview.toolReminder");
    if (node.type === "job" || /^[\da-f-]{24,}$/i.test(node.name))
      return t("sessionPreview.backgroundTask", { index: index + 1 });
    return previewText(node.name, 64);
  };
  return (
    <div className={styles.summary}>
      <Segmented
        value={lifecycle}
        aria-label={t("taskFilters.label")}
        onChange={(value) => {
          setLifecycle(String(value));
          setOffset(0);
        }}
        options={["active", "completed", "failed", "inactive", "all"].map(
          (value) => ({
            value,
            label: `${t(`taskFilters.${value}`)}${
              page?.counts[value] !== undefined ? ` ${page.counts[value]}` : ""
            }`,
          }),
        )}
      />
      <p className={styles.summaryCount}>
        {t(
          lifecycle === "active"
            ? "workspace0034.runningSummary"
            : "taskFilters.summary",
          {
            count: ids.size,
            jobs: jobs.length,
          },
        )}
      </p>
      {error && <Alert type="error" showIcon message={error} />}
      {!ids.size && (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("workspace0034.noBackgroundTasks")}
        />
      )}
      {[...ids].map((id) => {
        const thread = threads.get(id);
        const related = jobs.filter((job) => job.thread_id === id);
        const topic = localizedPreview(
          thread?.metadata?.one_liner,
          i18n?.resolvedLanguage ?? i18n?.language ?? "en",
        );
        const progress = localizedPreview(
          thread?.metadata?.current_progress ||
            thread?.metadata?.recent_events?.at(-1),
          i18n?.resolvedLanguage ?? i18n?.language ?? "en",
        );
        return (
          <section key={id} className={styles.threadCard}>
            <header>
              <MessageSquare size={16} />
              <strong>
                {previewText(
                  topic ||
                    thread?.title ||
                    page?.items.find((job) => job.thread_id === id)?.title ||
                    t("sessionPreview.taskFallback"),
                  80,
                )}
              </strong>
            </header>
            <div className={styles.cardState}>
              {lifecycle !== "active" && (
                <Tag>{t(`taskFilters.${lifecycle}`)}</Tag>
              )}
              {threads.has(id) && (
                <Tag color="processing">{t("chat.sessionWorkingShort")}</Tag>
              )}
              {related.length > 0 && (
                <span>
                  <Terminal size={13} />
                  {t("sessionPreview.backgroundCount", {
                    count: related.length,
                  })}
                </span>
              )}
            </div>
            {progress && <p className={styles.progress}>{progress}</p>}
            {related.some((job) => "stale" in job && job.stale) && (
              <p className={styles.muted}>
                {t("workspace0034.observationStale")}
              </p>
            )}
            <Button
              size="small"
              loading={busy === id}
              onClick={async () => {
                const request = ++epoch.current;
                setBusy(id);
                setError("");
                try {
                  const value = await activityApi.snapshot(agentId, id);
                  if (request !== epoch.current) return;
                  setSelected("");
                  setRecordState(lifecycle);
                  setLimit(8);
                  setDetail({ thread: id, value });
                } catch (e) {
                  if (request === epoch.current)
                    setError(apiErrorMessage(e, t("common.error"), t));
                } finally {
                  if (request === epoch.current) setBusy("");
                }
              }}
            >
              {t("sessionPreview.taskDetails")}
            </Button>
          </section>
        );
      })}
      {page && page.total > 20 && (
        <Pagination
          size="small"
          current={offset / 20 + 1}
          pageSize={20}
          total={page.total}
          showSizeChanger={false}
          onChange={(value) => setOffset((value - 1) * 20)}
        />
      )}
      <Modal
        open={Boolean(detail)}
        onCancel={() => setDetail(null)}
        footer={null}
        width={760}
        title={t("sessionPreview.taskObservations")}
        destroyOnHidden
      >
        {detail && (
          <div className={styles.observations}>
            {chosen ? (
              <>
                <Button
                  type="text"
                  icon={<ArrowLeft size={14} />}
                  onClick={() => setSelected("")}
                >
                  {t("workspace0034.backToTasks")}
                </Button>
                <NodeDetail
                  key={chosen.id}
                  node={chosen}
                  agentId={agentId}
                  threadId={detail.thread}
                />
              </>
            ) : (
              <>
                <div className={styles.counts}>
                  <Tag color="processing">
                    {t("sessionPreview.activeCount", {
                      count: nodes.filter((n) => n.status === "running").length,
                    })}
                  </Tag>
                  <Tag color="success">
                    {t("sessionPreview.completedCount", {
                      count: nodes.filter((n) => n.status === "completed")
                        .length,
                    })}
                  </Tag>
                  <Tag color="error">
                    {t("sessionPreview.failedCount", {
                      count: nodes.filter((n) => n.status === "failed").length,
                    })}
                  </Tag>
                </div>
                <Segmented
                  value={recordState}
                  aria-label={t("taskFilters.recordLabel")}
                  onChange={(value) => {
                    setRecordState(String(value));
                    setLimit(8);
                  }}
                  options={[
                    "active",
                    "completed",
                    "failed",
                    "inactive",
                    "all",
                  ].map((value) => ({
                    value,
                    label: t(`taskFilters.${value}`),
                  }))}
                />
                {detail.value.scope_truncated && (
                  <Alert type="info" message={t("workspace0034.truncated")} />
                )}
                {!visibleNodes.length && (
                  <Empty description={t("taskFilters.empty")} />
                )}
                <div className={styles.recordList}>
                  {visibleNodes.slice(0, limit).map((node, index) => (
                    <button
                      key={node.id}
                      className={styles.record}
                      onClick={() => setSelected(node.id)}
                    >
                      <strong>{nodeName(node, index)}</strong>
                      <ActivityStatus node={node} />
                      <time>
                        {formatMessageTime(node.updated_at * 1000, timezone)}
                      </time>
                    </button>
                  ))}
                </div>
                {visibleNodes.length > limit && (
                  <Button block onClick={() => setLimit((n) => n + 8)}>
                    {t("sessionPreview.olderRecords", {
                      count: visibleNodes.length - limit,
                    })}
                  </Button>
                )}
              </>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
