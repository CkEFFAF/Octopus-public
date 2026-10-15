import { useEffect, useRef, useState } from "react";
import { Alert, Button, Empty, Spin, Tag } from "antd";
import { RefreshCw, Square } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  executionApi,
  type ExecutionContext,
} from "../../../api/modules/execution";
import { base64ToBytes, formatBytes } from "../../Devices/helpers";
import styles from "./ExecutionWorkbench.module.less";

interface Job {
  job_id: string;
  argv: string[];
  cwd: string;
  status: string;
  observed_at: number;
  started_at?: number;
  returncode?: number;
  reason?: string;
  cancel_requested?: boolean;
  argv_truncated?: boolean;
  resources?: {
    rss_bytes: number;
    cpu_seconds: number;
    gpu?: {
      status: string;
      processes: {
        pid: number;
        gpu_uuid: string;
        memory_bytes: number | null;
      }[];
    };
  } | null;
}
interface Logs {
  data_b64: string;
  next_offset: number;
  status: string;
  truncated: boolean;
}

export default function ExecutionJobs({
  context,
  visible,
}: {
  context: ExecutionContext;
  visible: boolean;
}) {
  const { t } = useTranslation();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [output, setOutput] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [truncated, setTruncated] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [pages, setPages] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const offset = useRef(0);
  const decoder = useRef(new TextDecoder());
  useEffect(() => {
    if (!visible) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        if (!document.hidden) {
          const collected: Job[] = [];
          let position = 0,
            more = false;
          for (let page = 0; page < pages; page += 1) {
            const result = await executionApi.call<{
              jobs: Job[];
              has_more: boolean;
              next_offset?: number;
            }>(context.context_id, "jobs.list", {
              offset: position,
              limit: 50,
            });
            if (disposed) return;
            collected.push(...result.jobs);
            more = result.has_more;
            if (!more || !result.jobs.length) break;
            position = result.next_offset ?? position + result.jobs.length;
          }
          if (disposed) return;
          const unique = [
            ...new Map(collected.map((job) => [job.job_id, job])).values(),
          ];
          setJobs(unique);
          setHasMore(more);
          setError("");
          setSelected((value) => value ?? unique[0]?.job_id ?? null);
        }
      } catch (failure) {
        if (!disposed) setError(String(failure));
      } finally {
        if (!disposed) timer = setTimeout(() => void poll(), 2500);
      }
    }
    void poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [context.context_id, visible, refresh, pages]);
  useEffect(() => {
    offset.current = 0;
    decoder.current = new TextDecoder();
    setOutput("");
    setTruncated(false);
  }, [selected]);
  useEffect(() => {
    if (!selected || !visible) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        if (!document.hidden) {
          const result = await executionApi.call<Logs>(
            context.context_id,
            "jobs.logs",
            { job_id: selected, offset: offset.current },
          );
          if (disposed) return;
          offset.current = result.next_offset;
          const text = decoder.current.decode(base64ToBytes(result.data_b64), {
            stream: ["running", "queued", "unknown"].includes(result.status),
          });
          if (text)
            setOutput((value) => {
              const joined = value + text;
              if (joined.length > 128000) setTruncated(true);
              return joined.slice(-128000);
            });
          if (result.truncated) setTruncated(true);
        }
      } catch (failure) {
        if (!disposed) setError(String(failure));
      } finally {
        if (!disposed) timer = setTimeout(() => void poll(), 1500);
      }
    }
    void poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [context.context_id, selected, visible]);
  const job = jobs.find((item) => item.job_id === selected);
  async function cancel() {
    if (!job || busy) return;
    setBusy(true);
    try {
      const receipt = await executionApi.call<Job>(
        context.context_id,
        "jobs.cancel",
        { job_id: job.job_id },
      );
      setJobs((items) =>
        items.map((item) => (item.job_id === receipt.job_id ? receipt : item)),
      );
      setRefresh((value) => value + 1);
    } catch (failure) {
      setError(String(failure));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className={styles.jobs}>
      <div className={styles.actions}>
        <strong>{t("chat.execution.jobs")}</strong>
        <Button
          type="text"
          aria-label={t("common.refresh")}
          icon={<RefreshCw size={14} />}
          onClick={() => setRefresh((value) => value + 1)}
        />
      </div>
      {error && <Alert type="error" message={error} />}
      <div className={styles.jobBody}>
        <aside>
          {jobs.length === 0 && !error && (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("chat.execution.noJobs")}
            />
          )}
          {jobs.map((item) => (
            <button
              key={item.job_id}
              className={selected === item.job_id ? styles.selected : ""}
              onClick={() => setSelected(item.job_id)}
            >
              <b title={item.argv?.join(" ")}>
                {item.argv?.join(" ") || item.job_id}
                {item.argv_truncated && "…"}
              </b>
              <Tag>
                {t(`chat.execution.status.${item.status}`, item.status)}
              </Tag>
              <code>{item.job_id.slice(0, 8)}</code>
            </button>
          ))}
          {hasMore && (
            <Button onClick={() => setPages((value) => value + 1)}>
              {t("devices.native.more")}
            </Button>
          )}
        </aside>
        <section>
          {job ? (
            <>
              <div className={styles.jobDetails}>
                <code>{job.cwd}</code>
                <span>
                  {t("chat.execution.observed")}{" "}
                  {new Date(job.observed_at * 1000).toLocaleTimeString()}
                </span>
                {job.returncode != null && (
                  <span>
                    {t("chat.execution.exitCode")} {job.returncode}
                  </span>
                )}
                {job.resources && (
                  <span>
                    {formatBytes(job.resources.rss_bytes)} · CPU{" "}
                    {job.resources.cpu_seconds.toFixed(1)}s
                  </span>
                )}
                {job.resources?.gpu?.processes.map((process) => (
                  <span key={`${process.pid}:${process.gpu_uuid}`}>
                    GPU · PID {process.pid} · {process.gpu_uuid.slice(-8)} ·{" "}
                    {process.memory_bytes == null
                      ? "—"
                      : formatBytes(process.memory_bytes)}
                  </span>
                ))}
                {job.reason && <span>{job.reason}</span>}
                {job.cancel_requested &&
                  !["completed", "failed", "cancelled"].includes(
                    job.status,
                  ) && <span>{t("chat.execution.cancelPending")}</span>}
                {!["completed", "failed", "cancelled"].includes(job.status) &&
                  !["ask", "plan"].includes(context.work_mode) && (
                    <Button
                      size="small"
                      loading={busy}
                      icon={<Square size={12} />}
                      onClick={() => void cancel()}
                    >
                      {t("chat.execution.stop")}
                    </Button>
                  )}
              </div>
              {truncated && (
                <Alert type="info" message={t("chat.execution.logsBounded")} />
              )}
              <pre className={styles.logs}>
                {output || t("chat.execution.noOutput")}
              </pre>
            </>
          ) : (
            <Spin size="small" />
          )}
        </section>
      </div>
    </div>
  );
}
