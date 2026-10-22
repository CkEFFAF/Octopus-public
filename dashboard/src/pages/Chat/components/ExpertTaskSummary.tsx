import { useState } from "react";
import { Alert, Button, Empty, Space, Tag } from "antd";
import { useTranslation } from "react-i18next";
import { useSidebarActivity } from "../hooks/useSidebarActivity";
import {
  activityApi,
  type ActivitySnapshot,
} from "../../../api/modules/activity";
import { ActivityStatus } from "./TaskActivity";
import { apiErrorMessage } from "../../../utils/apiError";

export default function ExpertTaskSummary({
  agentId,
  threadId,
}: {
  agentId: string;
  threadId?: string;
}) {
  const { t } = useTranslation();
  const status = useSidebarActivity()[agentId];
  const [detail, setDetail] = useState<{
    thread: string;
    value: ActivitySnapshot;
  } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const threads = new Map(
    (status?.working_threads ?? [])
      .filter((r) => !threadId || r.thread_id === threadId)
      .map((r) => [r.thread_id, r.title || r.thread_id]),
  );
  const jobs = (status?.background_tasks ?? []).filter(
    (r) => !threadId || r.thread_id === threadId,
  );
  for (const job of jobs)
    if (!threads.has(job.thread_id)) threads.set(job.thread_id, job.thread_id);
  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      <p>
        {t("workspace0034.runningSummary", {
          count: threads.size,
          jobs: jobs.length,
        })}
      </p>
      {error && <Alert type="error" message={error} />}
      {!threads.size && (
        <Empty description={t("workspace0034.noBackgroundTasks")} />
      )}
      {[...threads].map(([id, title]) => (
        <section
          key={id}
          style={{
            padding: 16,
            border: "1px solid var(--fn-border-secondary)",
            borderRadius: 12,
          }}
        >
          <strong style={{ overflowWrap: "anywhere" }}>{title}</strong>
          {jobs
            .filter((j) => j.thread_id === id)
            .map((job) => (
              <p key={job.id}>
                <Tag color={job.stale ? "default" : "green"}>
                  {t(
                    job.stale
                      ? "workspace0034.observationStale"
                      : "chat.sessionWorkingShort",
                  )}
                </Tag>
                {job.name}
              </p>
            ))}
          <Button
            loading={busy === id}
            onClick={async () => {
              setBusy(id);
              setError("");
              try {
                setDetail({
                  thread: id,
                  value: await activityApi.snapshot(agentId, id),
                });
              } catch (e) {
                setError(apiErrorMessage(e, t("common.error"), t));
              } finally {
                setBusy("");
              }
            }}
          >
            {t("workspace0034.inspectTasks")}
          </Button>
          {detail?.thread === id &&
            detail.value.nodes.map((node) => (
              <p key={node.id}>
                <ActivityStatus node={node} /> {node.name}
              </p>
            ))}
        </section>
      ))}
    </Space>
  );
}
