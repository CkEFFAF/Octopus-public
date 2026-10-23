import { useEffect, useRef, useState } from "react";
import { Alert, Button, Empty, Modal, Tag } from "antd";
import { Terminal, MessageSquare, ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useSidebarActivity } from "../hooks/useSidebarActivity";
import {
  activityApi,
  type ActivityNode,
  type ActivitySnapshot,
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
  const epoch = useRef(0);
  useEffect(
    () => () => {
      ++epoch.current;
    },
    [agentId, threadId],
  );
  const threads = new Map(
    (status?.working_threads ?? [])
      .filter((r) => !threadId || r.thread_id === threadId)
      .map((r) => [r.thread_id, r]),
  );
  const jobs = (status?.background_tasks ?? []).filter(
    (r) => !threadId || r.thread_id === threadId,
  );
  const ids = new Set([...threads.keys(), ...jobs.map((job) => job.thread_id)]);
  const nodes = [...(detail?.value.nodes ?? [])].sort(
    (a, b) =>
      Number(b.status === "running") - Number(a.status === "running") ||
      b.updated_at - a.updated_at,
  );
  const chosen = nodes.find((node) => node.id === selected);
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
      <p className={styles.summaryCount}>
        {t("workspace0034.runningSummary", {
          count: ids.size,
          jobs: jobs.length,
        })}
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
                  topic || thread?.title || t("sessionPreview.taskFallback"),
                  80,
                )}
              </strong>
            </header>
            <div className={styles.cardState}>
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
            {related.some((job) => job.stale) && (
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
                {detail.value.scope_truncated && (
                  <Alert type="info" message={t("workspace0034.truncated")} />
                )}
                {!nodes.length && (
                  <Empty description={t("sessionPreview.recordsEmpty")} />
                )}
                <div className={styles.recordList}>
                  {nodes.slice(0, limit).map((node, index) => (
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
                {nodes.length > limit && (
                  <Button block onClick={() => setLimit((n) => n + 8)}>
                    {t("sessionPreview.olderRecords", {
                      count: nodes.length - limit,
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
