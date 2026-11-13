import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Empty,
  Input,
  Pagination,
  Segmented,
  Select,
  Skeleton,
  Tag,
  Tooltip,
} from "antd";
import { ArrowUpRight, RefreshCw } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  taskCenterApi,
  type TaskOverviewPage,
} from "../api/modules/taskCenter";
import { useAgent } from "../context/AgentContext";
import { useServerTimezone } from "../hooks/useServerTimezone";
import { formatServerDateTime } from "../utils/formatMessageTime";
import { apiErrorMessage } from "../utils/apiError";
import { WORK_ITEMS_CHANGED_EVENT } from "../utils/dashboardPushToast";
import styles from "./TaskOverview.module.less";

export default function TaskOverview({
  agentId = "",
  threadId = "",
  fixedAgent = false,
  onScopeChange,
}: {
  agentId?: string;
  threadId?: string;
  fixedAgent?: boolean;
  onScopeChange?: (agent: string, thread: string) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const timezone = useServerTimezone();
  const { agents } = useAgent();
  const [agent, setAgent] = useState(agentId);
  const [thread, setThread] = useState(threadId);
  const [lifecycle, setLifecycle] = useState("active");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<{
    key: string;
    value: TaskOverviewPage;
  } | null>(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const key = JSON.stringify({
    agent_id: agent,
    thread_id: thread,
    lifecycle,
    query,
    offset,
  });
  const identity = useRef(key);
  identity.current = key;
  const translate = useRef(t);
  translate.current = t;
  const current = page?.key === key ? page.value : null;
  useEffect(() => {
    setAgent(agentId);
    setThread(threadId);
    setOffset(0);
  }, [agentId, threadId]);
  useEffect(() => {
    let alive = true;
    let sequence = 0;
    let timer: ReturnType<typeof setTimeout>;
    setError("");
    async function load() {
      const request = ++sequence;
      try {
        const value = await taskCenterApi.page(JSON.parse(key));
        if (!alive || identity.current !== key || sequence !== request) return;
        if (offset > 0 && offset >= value.total) {
          setOffset(Math.floor(Math.max(0, value.total - 1) / 20) * 20);
          return;
        }
        setPage({ key, value });
        setError("");
      } catch (err) {
        if (alive && identity.current === key && sequence === request)
          setError(
            apiErrorMessage(
              err,
              translate.current("common.error"),
              translate.current,
            ),
          );
      } finally {
        // Completed and archived pages are stable and load only when requested.
        if (
          alive &&
          sequence === request &&
          ["active", "all"].includes(lifecycle)
        )
          timer = setTimeout(() => {
            if (!document.hidden) void load();
          }, 10000);
      }
    }
    const recover = () => {
      if (!document.hidden) {
        clearTimeout(timer);
        void load();
      }
    };
    const start = setTimeout(() => void load(), query ? 250 : 0);
    document.addEventListener("visibilitychange", recover);
    if (["active", "all"].includes(lifecycle))
      window.addEventListener(WORK_ITEMS_CHANGED_EVENT, recover);
    return () => {
      alive = false;
      clearTimeout(start);
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", recover);
      window.removeEventListener(WORK_ITEMS_CHANGED_EVENT, recover);
    };
  }, [key, refresh, lifecycle, offset, query]);
  const expertOptions = [
    ...new Map([
      ...agents.map(
        (item) =>
          [item.agent_id, { value: item.agent_id, label: item.name }] as const,
      ),
      ...(current?.agents ?? []).map((item) => [item.value, item] as const),
    ]).values(),
  ];
  const threads = current?.threads ?? page?.value.threads ?? [];
  return (
    <div className={styles.overview}>
      <div className={styles.filters}>
        {!fixedAgent && (
          <Select
            aria-label={t("taskCenter.expert")}
            showSearch
            optionFilterProp="label"
            value={agent}
            options={[
              { value: "", label: t("taskCenter.allExperts") },
              ...expertOptions,
            ]}
            onChange={(value) => {
              setAgent(value);
              setThread("");
              setOffset(0);
              onScopeChange?.(value, "");
            }}
          />
        )}
        <Select
          aria-label={t("taskCenter.conversation")}
          showSearch
          optionFilterProp="label"
          value={thread}
          options={[
            { value: "", label: t("taskCenter.allConversations") },
            ...threads.filter((item) => !agent || item.agent_id === agent),
          ]}
          onChange={(value) => {
            setThread(value);
            setOffset(0);
            onScopeChange?.(agent, value);
          }}
        />
        <Input.Search
          aria-label={t("taskCenter.search")}
          placeholder={t("taskCenter.search")}
          allowClear
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setOffset(0);
          }}
        />
        <Button
          icon={<RefreshCw size={15} />}
          aria-label={t("common.refresh")}
          onClick={() => setRefresh((value) => value + 1)}
        />
      </div>
      <div className={styles.states}>
        <Segmented
          aria-label={t("taskFilters.label")}
          value={lifecycle}
          options={[
            "active",
            "completed",
            "failed",
            "inactive",
            "all",
            "archived",
          ].map((value) => ({
            value,
            label: (
              <Tooltip
                title={
                  value === "archived"
                    ? t("taskCenter.retentionHint")
                    : undefined
                }
              >{`${t(`taskFilters.${value}`)}${
                current?.counts[value] !== undefined
                  ? ` ${current.counts[value]}`
                  : ""
              }`}</Tooltip>
            ),
          }))}
          onChange={(value) => {
            setLifecycle(String(value));
            setOffset(0);
          }}
        />
      </div>
      {error && (
        <Alert
          type="warning"
          showIcon
          message={error}
          action={
            <Button onClick={() => setRefresh((value) => value + 1)}>
              {t("common.retry")}
            </Button>
          }
        />
      )}
      {!current && !error && <Skeleton active paragraph={{ rows: 4 }} />}
      {current && current.items.length === 0 && (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("taskCenter.empty")}
        />
      )}
      {current && current.items.length > 0 && (
        <ul className={styles.tasks}>
          {current.items.map((item) => (
            <li key={item.id}>
              <div className={styles.taskMain}>
                <div className={styles.taskHeading}>
                  <strong>{item.title}</strong>
                  <Tag
                    color={
                      item.lifecycle === "active"
                        ? "processing"
                        : item.lifecycle === "failed"
                        ? "error"
                        : undefined
                    }
                  >
                    {item.stale
                      ? t("taskCenter.stale")
                      : t(`taskCenter.status.${item.status}`, {
                          defaultValue: item.status,
                        })}
                  </Tag>
                </div>
                {item.summary && (
                  <p className={styles.summary}>{item.summary}</p>
                )}
                <div className={styles.meta}>
                  <span>{item.agent_name || t("octopus.unassigned")}</span>
                  <span>{t(`taskCenter.sources.${item.source}`)}</span>
                  {item.declared && <span>{t("taskCenter.declared")}</span>}
                  <span>
                    {item.thread_title ||
                      item.thread_id ||
                      t("taskCenter.noConversation")}
                  </span>
                  <time>{formatServerDateTime(item.updated_at, timezone)}</time>
                </div>
              </div>
              <div className={styles.taskActions}>
                {item.source === "board" && (
                  <Button
                    size="small"
                    onClick={() =>
                      navigate(
                        `/task-board?task=${encodeURIComponent(
                          item.source_id,
                        )}`,
                      )
                    }
                  >
                    {t("taskCenter.openTask")}
                  </Button>
                )}
                {item.thread_id && (
                  <Button
                    size="small"
                    type="text"
                    icon={<ArrowUpRight size={14} />}
                    onClick={() =>
                      navigate(
                        `/chat/${encodeURIComponent(
                          item.agent_id,
                        )}/${encodeURIComponent(item.thread_id!)}`,
                      )
                    }
                  >
                    {t("taskCenter.openConversation")}
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {current && current.total > 20 && (
        <Pagination
          size="small"
          current={Math.floor(offset / 20) + 1}
          total={current.total}
          pageSize={20}
          showSizeChanger={false}
          onChange={(value) => setOffset((value - 1) * 20)}
        />
      )}
    </div>
  );
}
