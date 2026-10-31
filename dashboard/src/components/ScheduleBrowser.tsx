import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import {
  Alert,
  Button,
  Empty,
  Input,
  Select,
  Segmented,
  Skeleton,
  Tag,
} from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  Bell,
  CalendarClock,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  AlertCircle,
  Circle,
  Loader2,
  Copy,
  Bot,
  MessageSquare,
  ExternalLink,
} from "lucide-react";
import styles from "./ScheduleBrowser.module.less";
import {
  octopCronApi,
  type CronAttempt,
  type CronAttemptPage,
} from "../api/modules/cronjob";
import { useSchedulePage } from "../hooks/useSchedulePage";
import { useIsMobile } from "../hooks/useIsMobile";
import type { OctopCronRow } from "../api/types";

export function useSchedules(agentId: string, threadId?: string) {
  return useSchedulePage({ agent_id: agentId, thread_id: threadId });
}

function time(value: number | null | undefined, timezone?: string) {
  return value
    ? new Date(value * 1000).toLocaleString(undefined, { timeZone: timezone })
    : "—";
}

export function ScheduleDetail({
  item,
  agentId,
  onBack,
  currentThreadId,
  onNavigate,
}: {
  item: OctopCronRow;
  agentId: string;
  onBack?: () => void;
  currentThreadId?: string;
  onNavigate?: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const tabId = useId();
  const [page, setPage] = useState<CronAttemptPage | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState("records");
  const identity = `${agentId}\0${item.id}`;
  const currentIdentity = useRef({ identity, epoch: 0 });
  if (currentIdentity.current.identity !== identity) {
    currentIdentity.current = {
      identity,
      epoch: currentIdentity.current.epoch + 1,
    };
  }
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    let epoch = 0;
    setBusy(false);
    setTab("records");
    setPage(null);
    setError("");
    async function refresh() {
      const current = ++epoch;
      try {
        const fresh = await octopCronApi.attempts(agentId, item.id);
        if (!disposed && current === epoch) {
          setPage((old) =>
            old
              ? {
                  ...fresh,
                  items: Array.from(
                    new Map(
                      [...old.items, ...fresh.items].map((a) => [a.id, a]),
                    ).values(),
                  ).sort((a, b) => b.id - a.id),
                  has_more: old.has_more,
                  next_cursor: old.next_cursor,
                }
              : fresh,
          );
          setError("");
        }
      } catch (e) {
        if (!disposed && current === epoch) setError(String(e));
      } finally {
        if (!disposed && current === epoch)
          timer = setTimeout(
            () => void refresh(),
            document.hidden ? 30000 : 3000,
          );
      }
    }
    const visible = () => {
      if (!document.hidden) {
        clearTimeout(timer);
        void refresh();
      }
    };
    void refresh();
    document.addEventListener("visibilitychange", visible);
    return () => {
      disposed = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [agentId, item.id]);

  async function more() {
    if (!page?.next_cursor) return;
    const requestedEpoch = currentIdentity.current.epoch;
    setBusy(true);
    try {
      const next = await octopCronApi.attempts(
        agentId,
        item.id,
        page.next_cursor,
      );
      if (currentIdentity.current.epoch !== requestedEpoch) return;
      setPage((p) =>
        p ? { ...next, items: [...p.items, ...next.items] } : next,
      );
    } catch (e) {
      if (currentIdentity.current.epoch === requestedEpoch) setError(String(e));
    } finally {
      if (currentIdentity.current.epoch === requestedEpoch) setBusy(false);
    }
  }
  const chat = (thread: string, attempt?: CronAttempt) => {
    onNavigate?.();
    navigate(
      `/chat/${encodeURIComponent(agentId)}/${encodeURIComponent(thread)}`,
      {
        state: attempt
          ? {
              scheduleMessage: {
                threadId: thread,
                after: (attempt.started_at ?? attempt.created_at) * 1000,
                before: attempt.finished_at
                  ? attempt.finished_at * 1000
                  : undefined,
                excerpt: attempt.result_excerpt ?? "",
              },
            }
          : undefined,
      },
    );
  };
  const state = scheduleState(item);
  const purpose = schedulePurpose(item);
  const compact =
    item.self_reminder && state === "exhausted"
      ? item.last_run_at
        ? t("workspace0034.lastExecutedAt", {
            time: time(item.last_run_at, item.timezone),
          })
        : ""
      : state === "ended"
      ? t(
          item.last_status === "ok" && item.task_type === "text"
            ? "workspace0034.onceSent"
            : "workspace0034.onceEnded",
          { time: time(item.last_run_at, item.timezone) },
        )
      : item.next_run_at
      ? `${t("workspace0034.scheduleNext")} ${time(
          item.next_run_at,
          item.timezone,
        )} · ${readableTrigger(item.trigger, t)}`
      : state === "waiting_event"
      ? t("workspace0034.scheduleState.waiting_event")
      : item.last_run_at
      ? t("workspace0034.lastExecutedAt", {
          time: time(item.last_run_at, item.timezone),
        })
      : t(`workspace0034.scheduleState.${state}`);
  return (
    <section className={styles.detail}>
      {onBack && (
        <Button
          className={styles.back}
          type="text"
          icon={<ArrowLeft size={16} />}
          onClick={onBack}
        >
          {t("workspace0034.backToTasks")}
        </Button>
      )}
      <header className={styles.detailHeader}>
        <div className={styles.titleRow}>
          {item.self_reminder ? (
            <Bell size={18} />
          ) : (
            <CalendarClock size={18} />
          )}
          <h3>{purpose}</h3>
          {item.thread_id && item.thread_id !== currentThreadId && (
            <Button
              type="text"
              size="small"
              icon={<ExternalLink size={14} />}
              onClick={() => chat(item.thread_id!)}
            >
              {t("workspace0034.openConversation")}
            </Button>
          )}
        </div>
        <div className={styles.statusRow}>
          <span className={`${styles.statusDot} ${styles[state] ?? ""}`} />
          {!["ended", "exhausted"].includes(state) && (
            <span>{t(`workspace0034.scheduleState.${state}`)}</span>
          )}
          <ScheduleTag item={item} />
          {item.self_reminder && (
            <span className={styles.muted}>
              {t("workspace0034.executedCount", {
                fires: item.fires,
                max: item.max_fires,
              })}
            </span>
          )}
        </div>
        <p className={styles.scheduleLine}>
          {compact}{" "}
          <span className={styles.timezone} title={item.timezone}>
            {item.timezone}
          </span>
        </p>
        {item.kind === "daily_report" && item.report_options && (
          <div className={styles.muted}>
            <div>
              {t("cronJobs.form.reportNewConversation")}:{" "}
              {t(
                item.report_options.new_conversation
                  ? "cronJobs.col.freshThreadOn"
                  : "cronJobs.col.freshThreadOff",
              )}
            </div>
            <div>
              {t("cronJobs.form.reportIncludePrevious")}:{" "}
              {t(
                item.report_options.include_previous
                  ? "cronJobs.col.freshThreadOn"
                  : "cronJobs.col.freshThreadOff",
              )}
              {item.report_options.include_previous &&
                ` (${item.report_options.previous_count})`}
            </div>
          </div>
        )}
      </header>
      <div
        className={styles.tabs}
        role="tablist"
        aria-label={t("workspace0034.scheduleContent")}
      >
        {["records", "content"].map((value) => (
          <button
            key={value}
            role="tab"
            id={`${tabId}-tab-${value}`}
            aria-selected={tab === value}
            aria-controls={`${tabId}-schedule-${value}`}
            onClick={() => setTab(value)}
          >
            {t(
              value === "records"
                ? "workspace0034.executionRecords"
                : "workspace0034.scheduleContent",
            )}
          </button>
        ))}
      </div>
      {tab === "records" ? (
        <section
          id={`${tabId}-schedule-records`}
          aria-labelledby={`${tabId}-tab-records`}
          role="tabpanel"
          className={styles.records}
        >
          {error && (
            <Alert
              type="warning"
              message={t("workspace0034.observationUnavailable")}
            />
          )}
          {!page && !error ? (
            <Skeleton active paragraph={{ rows: 3 }} />
          ) : !page?.items.length ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("workspace0034.scheduleNoHistory")}
            />
          ) : (
            <ol className={styles.timeline}>
              {page.items.map((attempt) => (
                <AttemptResult
                  key={attempt.attempt_id}
                  attempt={attempt}
                  timezone={item.timezone}
                  onChat={chat}
                />
              ))}
            </ol>
          )}
          {page?.has_more && (
            <Button loading={busy} onClick={() => void more()}>
              {t("devices.native.more")}
            </Button>
          )}
          <p className={styles.hint}>
            {t("workspace0034.executionOutcomeHint")}
          </p>
        </section>
      ) : (
        <section
          id={`${tabId}-schedule-content`}
          aria-labelledby={`${tabId}-tab-content`}
          role="tabpanel"
          className={styles.content}
        >
          <ExpandableText
            key={item.self_reminder ? purpose : item.prompt}
            text={item.self_reminder ? purpose : item.prompt}
            clampClass={styles.clamped}
          />
          <div className={styles.contentActions}>
            <Button
              type="text"
              size="small"
              icon={<Copy size={14} />}
              onClick={() =>
                void navigator.clipboard.writeText(
                  item.self_reminder ? purpose : item.prompt,
                )
              }
            >
              {t("workspace0034.copyContent")}
            </Button>
          </div>
          {item.self_reminder && (
            <details className={styles.secondary}>
              <summary>{t("workspace0034.fullInstruction")}</summary>
              <p>{item.prompt}</p>
            </details>
          )}
          <details className={styles.secondary}>
            <summary>{t("workspace0034.scheduleSettings")}</summary>
            <p>
              {readableTrigger(item.trigger, t)} · {item.timezone}
            </p>
            <p>{t(`workspace0034.scheduleState.${state}`)}</p>
            <p>
              {t(
                item.self_reminder
                  ? "workspace0034.reminderReadOnly"
                  : "workspace0034.scheduleSource",
              )}
            </p>
            {!item.thread_id && <p>{t("workspace0034.scheduleUnlinked")}</p>}
          </details>
        </section>
      )}
      <details className={styles.technical}>
        <summary>{t("workspace0034.technical")}</summary>
        <pre>
          {JSON.stringify(
            {
              id: item.id,
              agent: item.agent_id,
              thread: item.thread_id,
              trigger: item.trigger,
              scheduler_state: item.scheduler_state,
              observed_at: item.observed_at,
              last_error: item.last_error,
              attempts: page?.items.map(
                ({
                  attempt_id,
                  run_id,
                  source_thread_id,
                  actual_thread_id,
                  started_at,
                  finished_at,
                  public_error,
                }) => ({
                  attempt_id,
                  run_id,
                  source_thread_id,
                  actual_thread_id,
                  started_at,
                  finished_at,
                  public_error,
                }),
              ),
            },
            null,
            2,
          )}
        </pre>
      </details>
    </section>
  );
}

function AttemptResult({
  attempt,
  timezone,
  onChat,
}: {
  attempt: CronAttempt;
  timezone?: string;
  onChat: (thread: string, attempt?: CronAttempt) => void;
}) {
  const { t } = useTranslation();
  const Icon =
    attempt.status === "running"
      ? Loader2
      : ["completed", "delivered"].includes(attempt.status)
      ? CheckCircle2
      : ["failed", "unknown"].includes(attempt.status)
      ? AlertCircle
      : Circle;
  const conversation = attempt.actual_thread_id ? (
    <Button
      type="link"
      size="small"
      onClick={() => onChat(attempt.actual_thread_id!, attempt)}
    >
      {t("workspace0034.viewConversation")}
    </Button>
  ) : null;
  return (
    <li data-status={attempt.status}>
      <div className={styles.attemptHeader}>
        <Icon
          size={16}
          className={attempt.status === "running" ? styles.spinning : ""}
        />
        <strong>{t(`workspace0034.attemptStatus.${attempt.status}`)}</strong>
        <time>
          {time(
            attempt.finished_at ?? attempt.started_at ?? attempt.created_at,
            timezone,
          )}
        </time>
      </div>
      {attempt.public_error ? (
        <>
          <p>
            {t(
              attempt.status === "unknown"
                ? "workspace0034.scheduleInterrupted"
                : "workspace0034.scheduleDeliveryFailed",
            )}
          </p>
          <details className={styles.errorDetail}>
            <summary>{t("workspace0034.showError")}</summary>
            <p>{attempt.public_error}</p>
          </details>
        </>
      ) : attempt.result_excerpt ? (
        <ExpandableText
          key={attempt.result_excerpt}
          text={attempt.result_excerpt}
          clampClass={styles.resultClamped}
          actions={conversation}
        />
      ) : (
        <p className={styles.muted}>
          {t(
            ["completed", "delivered"].includes(attempt.status)
              ? "workspace0034.noPublicOutput"
              : `workspace0034.attemptStatus.${attempt.status}`,
          )}
        </p>
      )}
      {(!attempt.result_excerpt || attempt.public_error) && conversation && (
        <div className={styles.contentActions}>{conversation}</div>
      )}
    </li>
  );
}

export function ExpandableText({
  text,
  clampClass,
  actions,
}: {
  text: string;
  clampClass: string;
  actions?: ReactNode;
}) {
  const { t } = useTranslation();
  const element = useRef<HTMLParagraphElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [overflowing, setOverflowing] = useState(false);
  useEffect(() => {
    const paragraph = element.current;
    if (!paragraph || expanded) return;
    const measure = () =>
      setOverflowing(paragraph.scrollHeight > paragraph.clientHeight + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(paragraph);
    return () => observer.disconnect();
  }, [text, expanded]);
  return (
    <>
      <p ref={element} className={expanded ? "" : clampClass}>
        {text}
      </p>
      {(overflowing || actions) && (
        <div className={styles.contentActions}>
          {overflowing && (
            <Button
              size="small"
              type="text"
              icon={
                expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />
              }
              onClick={() => setExpanded((value) => !value)}
            >
              {t(expanded ? "workspace0034.collapse" : "workspace0034.expand")}
            </Button>
          )}
          {actions}
        </div>
      )}
    </>
  );
}

export function schedulePurpose(item: OctopCronRow): string {
  const purpose = item.meta?.purpose;
  return item.self_reminder && typeof purpose === "string" && purpose.trim()
    ? purpose.trim()
    : item.self_reminder
    ? item.name.replace(/^self-check:\s*/, "")
    : item.name;
}

export function scheduleState(item: OctopCronRow): string {
  const current = item.scheduler_state ?? "unregistered";
  if (item.self_reminder || current !== "unregistered") return current;
  if (item.last_status === "error") return "last_failed";
  const scheduled = item.trigger.startsWith("date:")
    ? Date.parse(item.trigger.slice(5)) / 1000
    : NaN;
  if (
    !item.next_run_at &&
    Number.isFinite(scheduled) &&
    item.observed_at != null &&
    scheduled <= item.observed_at &&
    item.last_status === "ok" &&
    item.last_run_at != null &&
    item.last_run_at >= scheduled &&
    item.last_run_at <= item.observed_at
  )
    return "ended";
  return current;
}

function readableTrigger(
  trigger: string,
  t: (key: string, options?: Record<string, unknown>) => string,
) {
  if (trigger.startsWith("interval:")) {
    const seconds = Number(trigger.slice(9));
    return t("workspace0034.everySeconds", { count: seconds });
  }
  if (trigger.startsWith("date:")) return t("workspace0034.scheduleOnce");
  if (trigger.startsWith("agently:")) return t("workspace0034.mailTrigger");
  return trigger.replace(/^cron:/, "Cron · ");
}

function scheduleCategory(item: OctopCronRow) {
  return (
    item.category ??
    (["ended", "exhausted"].includes(scheduleState(item))
      ? "ended"
      : item.trigger.startsWith("date:")
      ? "once"
      : "repeat")
  );
}

export function ScheduleTag({ item }: { item: OctopCronRow }) {
  const { t } = useTranslation();
  const category = scheduleCategory(item);
  return (
    <>
      <Tag
        color={
          category === "once"
            ? "blue"
            : category === "repeat"
            ? "purple"
            : "default"
        }
      >
        {t(`workspace0034.category.${category}`)}
      </Tag>
      {item.kind === "daily_report" && (
        <Tag>{t("cronJobs.form.taskTypeReport")}</Tag>
      )}
    </>
  );
}

export default function ScheduleBrowser({
  agentId,
  threadId,
  reminder = false,
  onScopeChange,
  global = false,
  onManage,
  onNavigate,
  compact = false,
}: {
  agentId?: string;
  threadId?: string;
  reminder?: boolean;
  onScopeChange?: (scope: string) => void;
  global?: boolean;
  onManage?: (item: OctopCronRow) => void;
  onNavigate?: () => void;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const [lifecycle, setLifecycle] = useState("active");
  const [scope, setScope] = useState("thread");
  const [category, setCategory] = useState<
    "once" | "repeat" | "ended" | undefined
  >();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search), 250);
    return () => clearTimeout(timer);
  }, [search]);
  const {
    items: rows,
    total,
    error,
    loading,
    has_more,
    loadingMore,
    loadMore,
    refresh,
    lifecycle_counts,
  } = useSchedulePage({
    agent_id: agentId,
    thread_id: scope === "thread" ? threadId : undefined,
    reminder,
    category,
    search: query,
    lifecycle:
      lifecycle === "all"
        ? undefined
        : (lifecycle as "active" | "completed" | "failed" | "inactive"),
  });
  const [selected, setSelected] = useState("");
  const current = rows.find((i) => `${i.agent_id}:${i.id}` === selected);
  useEffect(() => {
    setSelected("");
    setScope("thread");
  }, [agentId, threadId, reminder]);
  return (
    <div className={`${styles.browser} ${compact ? styles.compact : ""}`}>
      <div className={styles.scope}>
        {threadId ? (
          <Segmented
            value={scope}
            onChange={(v) => {
              setScope(String(v));
              onScopeChange?.(String(v));
              setSelected("");
            }}
            options={[
              { value: "thread", label: t("workspace0034.scheduleCurrent") },
              { value: "agent", label: t("workspace0034.scheduleAll") },
            ]}
          />
        ) : (
          <span className={styles.scopeTitle}>
            {reminder ? <Bell size={15} /> : <CalendarClock size={15} />}
            {t(
              global
                ? "workspace0034.allConversations"
                : "workspace0034.scheduleAll",
            )}
          </span>
        )}
        <small className={styles.totalBadge}>
          {loading
            ? t("workspace0034.loading")
            : t("workspace0034.scheduleTotal", { count: total })}
        </small>
      </div>
      <div className={styles.lifecycleFilters}>
        <Segmented
          value={lifecycle}
          aria-label={t("taskFilters.label")}
          onChange={(value) => {
            setLifecycle(String(value));
            setSelected("");
          }}
          options={["active", "completed", "failed", "inactive", "all"].map(
            (value) => ({
              value,
              label: `${t(`taskFilters.${value}`)}${
                lifecycle_counts?.[value] !== undefined
                  ? ` ${lifecycle_counts[value]}`
                  : ""
              }`,
            }),
          )}
        />
      </div>
      <div className={styles.filters}>
        <Input.Search
          allowClear
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t("workspace0034.searchSchedules")}
          aria-label={t("workspace0034.searchSchedules")}
        />
        {!compact && (
          <Select
            value={category ?? "all"}
            aria-label={t("workspace0034.filterCategory")}
            onChange={(value) => {
              setCategory(
                value === "all"
                  ? undefined
                  : (value as "once" | "repeat" | "ended"),
              );
              setSelected("");
            }}
            options={["all", "once", "repeat"].map((value) => ({
              value,
              label: t(`workspace0034.category.${value}`),
            }))}
          />
        )}
      </div>
      <p className={styles.sortHint}>
        {t(
          lifecycle === "all"
            ? "workspace0034.sortHint"
            : lifecycle === "active"
            ? "taskFilters.activeHint"
            : "taskFilters.detailHint",
        )}
      </p>
      {error && (
        <Alert
          type="warning"
          message={t("workspace0034.observationUnavailable")}
          showIcon
          action={
            <Button onClick={() => void refresh()}>
              {t("common.refresh")}
            </Button>
          }
        />
      )}
      {loading ? (
        <div className={styles.detail}>
          <Skeleton active paragraph={{ rows: 7 }} />
        </div>
      ) : !rows.length ? (
        <div className={styles.empty}>
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={t("workspace0034.scheduleEmpty")}
          />
        </div>
      ) : (
        <div
          className={`${styles.columns} ${
            isMobile && current ? styles.mobileDetail : ""
          } ${compact && !current ? styles.cardList : ""} ${
            compact && current ? styles.compactDetail : ""
          }`}
        >
          <nav
            className={styles.list}
            aria-label={t(
              reminder ? "workspace0034.reminders" : "workspace0034.schedules",
            )}
          >
            {rows.map((item) => {
              const identity = `${item.agent_id}:${item.id}`;
              return (
                <button
                  key={identity}
                  className={`${styles.row} ${
                    selected === identity ? styles.selected : ""
                  }`}
                  onClick={() => setSelected(identity)}
                  aria-pressed={selected === identity}
                >
                  <span
                    className={styles.taskIcon}
                    data-category={scheduleCategory(item)}
                  >
                    {reminder ? (
                      <Bell size={16} />
                    ) : (
                      <CalendarClock size={16} />
                    )}
                  </span>
                  <span className={styles.text}>
                    <strong>{schedulePurpose(item)}</strong>
                    <span className={styles.rowState}>
                      <ScheduleTag item={item} />
                      {!["ended", "exhausted"].includes(scheduleState(item)) &&
                        t(`workspace0034.scheduleState.${scheduleState(item)}`)}
                    </span>
                    {global && (
                      <span className={styles.rowContext}>
                        <span>
                          <Bot size={12} />
                          {item.agent_name ?? item.agent_id}
                        </span>
                        <span
                          title={
                            item.thread_title || item.thread_id || undefined
                          }
                        >
                          <MessageSquare size={12} />
                          {item.thread_title ||
                            item.thread_id ||
                            t("workspace0034.scheduleUnlinked")}
                        </span>
                      </span>
                    )}
                    {!item.next_run_at && !item.trigger.startsWith("date:") && (
                      <small>{readableTrigger(item.trigger, t)}</small>
                    )}
                    <small>
                      {item.next_run_at
                        ? `${t("workspace0034.scheduleNext")} ${time(
                            item.next_run_at,
                            item.timezone,
                          )} · ${readableTrigger(item.trigger, t)}`
                        : item.self_reminder &&
                          scheduleState(item) === "exhausted"
                        ? t("workspace0034.executedCount", {
                            fires: item.fires,
                            max: item.max_fires,
                          })
                        : item.last_run_at
                        ? time(item.last_run_at, item.timezone)
                        : t("workspace0034.noExecutionYet")}
                    </small>
                    {threadId && item.thread_id !== threadId && (
                      <small>{t("workspace0034.otherConversation")}</small>
                    )}
                  </span>
                </button>
              );
            })}
            {has_more && (
              <Button
                block
                loading={loadingMore}
                onClick={() => void loadMore()}
              >
                {t("workspace0034.moreFive")}
              </Button>
            )}
          </nav>
          {current ? (
            <div className={styles.detailPane}>
              {onManage && current.capabilities?.manage && (
                <Button
                  className={styles.manageButton}
                  onClick={() => onManage(current)}
                >
                  {t("workspace0034.scheduleManage")}
                </Button>
              )}
              <ScheduleDetail
                key={`${current.agent_id}:${current.id}`}
                item={current}
                agentId={current.agent_id}
                currentThreadId={threadId}
                onNavigate={onNavigate}
                onBack={() => setSelected("")}
              />
            </div>
          ) : !compact ? (
            <div className={styles.empty}>
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t("workspace0034.selectSchedule")}
              />
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
