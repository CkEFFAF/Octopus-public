import { useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import {
  Alert,
  Button,
  Modal,
  Popover,
  Skeleton,
  Segmented,
  Empty,
  Tag,
} from "antd";
import {
  Activity,
  CheckCircle2,
  Clock3,
  LoaderCircle,
  PauseCircle,
  Terminal,
  GitFork,
  Bot,
  CalendarClock,
  ArrowUpRight,
  X,
  Bell,
  ArrowLeft,
  XCircle,
} from "lucide-react";
import Markdown from "../../../components/Markdown";
import { publicText } from "../utils/publicMessageText";
import { useServerTimezone } from "../../../hooks/useServerTimezone";
import { useTranslation } from "react-i18next";
import {
  activityApi,
  type ActivityNode,
  type ActivitySnapshot,
} from "../../../api/modules/activity";
import {
  collaborationApi,
  type CollaborationDetail,
} from "../../../api/modules/collaboration";
import { base64ToBytes } from "../../Devices/helpers";
import { executionApi } from "../../../api/modules/execution";
import ScheduleBrowser, {
  useSchedules,
} from "../../../components/ScheduleBrowser";
import TaskActivityGraph from "./TaskActivityGraph";
import styles from "./TaskActivity.module.less";

export const OPEN_TASK_ACTIVITY_EVENT = "octop:open-task-activity";

export function ActivityStatus({
  node,
  stale = false,
}: {
  node: ActivityNode;
  stale?: boolean;
}) {
  const { t } = useTranslation();
  const outdated = stale || node.observed_status === "stale";
  const running = node.status === "running" && !outdated;
  const Icon = outdated
    ? Clock3
    : running
    ? LoaderCircle
    : node.status === "completed"
    ? CheckCircle2
    : node.status === "failed"
    ? XCircle
    : node.status === "cancelled"
    ? PauseCircle
    : Clock3;
  return (
    <span className={styles.status}>
      <Icon size={15} className={running ? styles.running : ""} />
      {t(`workspace0034.status.${outdated ? "stale" : node.status}`)}
    </span>
  );
}

export function NodeDetail({
  node,
  agentId,
  threadId,
  stale = false,
}: {
  node: ActivityNode;
  stale?: boolean;
  agentId: string;
  threadId: string;
}) {
  const { t } = useTranslation();
  const timezone = useServerTimezone();
  const [detail, setDetail] = useState<CollaborationDetail | null>(null);
  const [log, setLog] = useState("");
  const [logsLoaded, setLogsLoaded] = useState(false);
  const [cursor, setCursor] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const epoch = useRef(0);
  useEffect(() => {
    const lifecycleEpoch = epoch;
    const current = ++lifecycleEpoch.current;
    setBusy(false);
    setDetail(null);
    setLog("");
    setLogsLoaded(false);
    setCursor(0);
    setError("");
    if (node.type === "delegation")
      void collaborationApi
        .detail(agentId, threadId, node.id)
        .then((value) => {
          if (current === epoch.current) setDetail(value);
        })
        .catch((e) => {
          if (current === epoch.current) setError(String(e));
        });
    return () => {
      ++lifecycleEpoch.current;
    };
  }, [agentId, threadId, node.id, node.type]);
  async function logs() {
    if (!node.context_id) return;
    const current = epoch.current;
    setBusy(true);
    try {
      const result = await executionApi.call<{
        data_b64?: string;
        stdout?: string;
        stderr?: string;
        next_offset?: number;
        truncated?: boolean;
      }>(node.context_id, "jobs.logs", {
        job_id: node.details?.job_id,
        offset: cursor,
        length: 65536,
      });
      if (current !== epoch.current) return;
      setLogsLoaded(true);
      setLog(
        (v) =>
          v +
          (result.data_b64
            ? new TextDecoder().decode(base64ToBytes(result.data_b64))
            : "") +
          (result.stdout ?? "") +
          (result.stderr ?? ""),
      );
      setCursor(result.next_offset ?? cursor);
      if (result.truncated)
        setLog((v) => v + `\n[${t("workspace0034.truncated")}]\n`);
    } catch (e) {
      if (current === epoch.current) setError(String(e));
    } finally {
      if (current === epoch.current) setBusy(false);
    }
  }
  async function moreMessages() {
    if (!detail) return;
    const current = epoch.current;
    try {
      const page = await collaborationApi.detail(
        agentId,
        threadId,
        node.id,
        detail.next_before ?? undefined,
      );
      if (current === epoch.current)
        setDetail((old) =>
          old
            ? { ...page, messages: [...old.messages, ...page.messages] }
            : page,
        );
    } catch (e) {
      if (current === epoch.current) setError(String(e));
    }
  }
  return (
    <section className={styles.detail}>
      <h3>
        {node.type === "job" ? t("workspace0034.nodeType.job") : node.name}
      </h3>
      <p>
        {node.type === "job"
          ? `#${String(node.details?.job_id ?? node.name).slice(-8)}`
          : String(
              node.details?.subagent_type ??
                node.details?.device_id ??
                t(`workspace0034.nodeType.${node.type}`),
            )}
      </p>
      <ActivityStatus node={node} stale={stale} />
      {node.declared_status && (
        <p>
          {t("workspace0034.declared")}: {node.declared_status}
        </p>
      )}
      {node.reason && <p>{node.reason}</p>}
      {!node.dependencies_known && (
        <Alert type="info" message={t("workspace0034.dependenciesUnknown")} />
      )}
      {error && (
        <Alert
          type="warning"
          message={t("workspace0034.observationUnavailable")}
        />
      )}
      {node.type === "delegation" && (
        <>
          <p>{String(node.details?.prompt ?? "")}</p>
          {detail?.messages
            .filter(
              (m) =>
                ["user", "assistant"].includes(m.role) && publicText(m.content),
            )
            .map((m) => (
              <article key={m.seq}>
                <Tag>{t(`workspace0034.role.${m.role}`)}</Tag>
                <small>
                  {new Date(m.created_at * 1000).toLocaleString(undefined, {
                    timeZone: timezone,
                  })}
                </small>
                <Markdown content={publicText(m.content)} />
              </article>
            ))}
          {detail?.has_more && (
            <Button onClick={() => void moreMessages()}>
              {t("devices.native.more")}
            </Button>
          )}
        </>
      )}
      {node.type === "subagent" && (
        <>
          <p>{t("workspace0034.nativePublicScope")}</p>
          <h4>{t("workspace0034.publicInput")}</h4>
          <pre>
            {publicText(node.details?.public_prompt) ||
              t("workspace0034.noPublicOutput")}
          </pre>
          <h4>{t("workspace0034.publicProgress")}</h4>
          <pre>
            {String(
              node.details?.public_progress ??
                t("workspace0034.noPublicOutput"),
            )}
          </pre>
          <h4>{t("workspace0034.publicReply")}</h4>
          <pre>
            {publicText(node.details?.public_reply) ||
              t("workspace0034.noPublicOutput")}
          </pre>
          {node.details?.public_truncated === true && (
            <Alert type="info" message={t("workspace0034.truncated")} />
          )}
        </>
      )}
      {node.type === "job" && (
        <>
          <Button loading={busy} onClick={() => void logs()}>
            {t("workspace0034.loadLogs")}
          </Button>
          <small>
            {t("workspace0034.logOffset")}: {cursor}
          </small>
          <pre>
            {log ||
              t(
                logsLoaded
                  ? "workspace0034.noLogContent"
                  : "workspace0034.logsNotLoaded",
              )}
          </pre>
        </>
      )}
      {node.details && (
        <details>
          <summary>{t("workspace0034.technical")}</summary>
          <pre>
            {JSON.stringify(
              {
                run: node.run_id,
                attempt: node.attempt_id,
                context: node.context_id,
                receipt: node.details,
              },
              null,
              2,
            )}
          </pre>
        </details>
      )}
    </section>
  );
}

export default function TaskActivity({
  agentId,
  threadId,
  compact = false,
}: {
  agentId: string;
  threadId: string;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  const timezone = useServerTimezone();
  const [scheduleScope, setScheduleScope] = useState("thread");
  const route = useParams<{ agentId: string; threadId: string }>();
  const [search, setSearch] = useSearchParams();
  const requestedSection = search.get("task_view");
  const matchesRoute = route.agentId === agentId && route.threadId === threadId;
  const schedules = useSchedules(agentId, threadId);
  const navSchedules = useSchedules(
    agentId,
    scheduleScope === "agent" ? undefined : threadId,
  );
  const [snapshot, setSnapshot] = useState<ActivitySnapshot | null>(null);
  const [error, setError] = useState("");
  const [summary, setSummary] = useState(false);
  const [open, setOpen] = useState(false);
  const [fullscreen, setFullscreen] = useState(
    () => window.matchMedia("(max-width: 650px)").matches,
  );
  useEffect(() => {
    const query = window.matchMedia("(max-width: 650px)");
    const changed = () => setFullscreen(query.matches);
    query.addEventListener("change", changed);
    changed();
    return () => query.removeEventListener("change", changed);
  }, []);
  const [section, setSection] = useState("live");
  useEffect(() => {
    if (
      !matchesRoute ||
      !["schedules", "reminders"].includes(requestedSection ?? "")
    ) {
      setOpen(false);
      return;
    }
    clearTimeout(clickTimer.current);
    setSummary(false);
    setScheduleScope("thread");
    setSection(requestedSection!);
    setOpen(true);
  }, [matchesRoute, requestedSection, agentId, threadId]);
  const [filter, setFilter] = useState("all");
  const [view, setView] = useState("auto");
  const [selected, setSelected] = useState("");
  useEffect(() => {
    const show = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      if (detail?.agentId !== agentId || detail?.threadId !== threadId) return;
      setSummary(false);
      setSection("live");
      setSelected(detail.nodeId ?? "");
      setOpen(true);
    };
    window.addEventListener(OPEN_TASK_ACTIVITY_EVENT, show);
    return () => window.removeEventListener(OPEN_TASK_ACTIVITY_EVENT, show);
  }, [agentId, threadId]);
  const [older, setOlder] = useState<ActivityNode[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [historyBusy, setHistoryBusy] = useState(false);
  const scopeIdentity = JSON.stringify([agentId, threadId]);
  const currentScope = useRef<string | null>(scopeIdentity);
  currentScope.current = scopeIdentity;
  const entry = useRef<HTMLButtonElement>(null);
  const summaryHost = useRef<HTMLDivElement>(null);
  const clickTimer = useRef<ReturnType<typeof setTimeout>>();
  const touch = useRef(false);
  useEffect(() => () => clearTimeout(clickTimer.current), []);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    let epoch = 0;
    currentScope.current = scopeIdentity;
    setHistoryBusy(false);
    setSnapshot(null);
    setOlder([]);
    setCursor(null);
    setSelected("");
    async function refresh() {
      const current = ++epoch;
      try {
        const next = await activityApi.snapshot(agentId, threadId);
        if (!disposed && current === epoch) {
          setSnapshot(next);
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
      currentScope.current = null;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [agentId, threadId, scopeIdentity]);
  useEffect(() => {
    if (!summary) return;
    const outside = (event: PointerEvent) => {
      const target = event.target as Node;
      if (
        !entry.current?.contains(target) &&
        !summaryHost.current?.contains(target)
      )
        setSummary(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSummary(false);
        entry.current?.focus();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [summary]);
  const stale =
    Boolean(error) ||
    Boolean(snapshot && Date.now() / 1000 - snapshot.observed_at > 45);
  const nodes = Array.from(
    new Map(
      [...older, ...(snapshot?.nodes ?? [])].map((n) => [n.id, n]),
    ).values(),
  );
  const running =
    snapshot?.nodes.filter(
      (n) =>
        ["subagent", "delegation", "job"].includes(n.type) &&
        n.status === "running" &&
        n.observed_status === "current",
    ) ?? [];
  const runningAgents = running.filter((n) => n.type !== "job").length;
  const runningJobs = running.filter((n) => n.type === "job").length;
  const selectedNode = nodes.find((n) => n.id === selected);
  const scheduleCount =
    schedules.loading || schedules.error ? "?" : schedules.counts.schedules;
  const reminderCount =
    schedules.loading || schedules.error ? "?" : schedules.counts.reminders;
  const nextSchedule =
    schedules.next_schedule ??
    schedules.items
      .filter((i) => i.next_run_at)
      .sort((a, b) => a.next_run_at! - b.next_run_at!)[0];
  const nextTime = nextSchedule?.next_run_at
    ? new Date(nextSchedule.next_run_at * 1000).toLocaleTimeString(undefined, {
        timeZone: nextSchedule.timezone,
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;
  const entryText = snapshot?.active_scope_truncated
    ? t("workspace0034.partialActivity")
    : stale
    ? t("workspace0034.observationUnavailable")
    : runningAgents
    ? t("workspace0034.runningAgents", { count: runningAgents })
    : runningJobs
    ? t("workspace0034.runningJobs", { count: runningJobs })
    : snapshot?.counts.subagents
    ? t("workspace0034.waitingAgents", { count: snapshot.counts.subagents })
    : snapshot?.counts.jobs
    ? t("workspace0034.waitingJobs", { count: snapshot.counts.jobs })
    : nextTime
    ? t("workspace0034.nextAt", { time: nextTime })
    : t("workspace0034.tasks");
  const filtered = nodes.filter(
    (n) =>
      filter === "all" ||
      (filter === "agents" && ["subagent", "delegation"].includes(n.type)) ||
      (filter === "jobs" && n.type === "job"),
  );
  const plans = Boolean(snapshot?.nodes.some((n) => n.type === "plan"));
  const graph = view === "graph" || (view === "auto" && plans);
  function details() {
    clearTimeout(clickTimer.current);
    setSummary(false);
    setOpen(true);
  }
  function close() {
    setOpen(false);
    if (matchesRoute && search.has("task_view")) {
      const next = new URLSearchParams(search);
      next.delete("task_view");
      setSearch(next, { replace: true });
    }
    entry.current?.focus();
  }
  async function loadOlder() {
    const before = cursor ?? snapshot?.next_before;
    if (!before || before < 0) return;
    const identity = scopeIdentity;
    setHistoryBusy(true);
    try {
      const page = await activityApi.snapshot(agentId, threadId, before);
      if (currentScope.current !== identity) return;
      setOlder((old) =>
        Array.from(
          new Map([...old, ...page.nodes].map((n) => [n.id, n])).values(),
        ),
      );
      setCursor(page.next_before ?? -1);
    } catch (e) {
      if (currentScope.current === identity) setError(String(e));
    } finally {
      if (currentScope.current === identity) setHistoryBusy(false);
    }
  }
  const list = (
    <div className={styles.runList}>
      {filtered.map((node) => (
        <button
          key={node.id}
          className={`${styles.runRow} ${
            selected === node.id ? styles.selected : ""
          }`}
          onClick={() => setSelected(node.id)}
        >
          <span className={styles.rowIcon}>
            {node.type === "job" ? (
              <Terminal size={18} />
            ) : node.type === "plan" ? (
              <GitFork size={18} />
            ) : (
              <Bot size={18} />
            )}
          </span>
          <span className={styles.rowMain}>
            <strong>{node.name}</strong>
            <small>
              {String(
                node.details?.subagent_type ??
                  node.details?.device_id ??
                  t(`workspace0034.nodeType.${node.type}`),
              )}
            </small>
            <p>
              {String(
                node.details?.public_progress ??
                  node.details?.public_reply ??
                  node.reason ??
                  "",
              ).slice(0, 140)}
            </p>
          </span>
          <span className={styles.rowStatus}>
            <ActivityStatus node={node} stale={stale} />
            <small>
              {new Date(node.updated_at * 1000).toLocaleTimeString(undefined, {
                timeZone: timezone,
                hour: "2-digit",
                minute: "2-digit",
              })}
            </small>
          </span>
        </button>
      ))}
      {!filtered.length && (
        <div className={styles.empty}>
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={t("workspace0034.noActivity")}
          />
        </div>
      )}
      {(cursor ?? snapshot?.next_before) && cursor !== -1 && (
        <Button loading={historyBusy} onClick={() => void loadOlder()}>
          {t("devices.native.more")}
        </Button>
      )}
    </div>
  );
  const summaryContent = (
    <div className={styles.summary} ref={summaryHost}>
      <div className={styles.summaryHeader}>
        <b>{entryText}</b>
        {snapshot?.active_scope_truncated && (
          <p>{t("workspace0034.activeWindow")}</p>
        )}
        <span>{t("workspace0034.scopeCurrent")}</span>
      </div>
      {!snapshot && !error ? (
        <Skeleton active paragraph={{ rows: 2 }} />
      ) : (
        <>
          <div className={styles.summaryCounts}>
            <span>
              {t("workspace0034.subagents", {
                count: snapshot?.counts.subagents ?? "?",
              })}
            </span>
            <span>
              {t("workspace0034.jobs", { count: snapshot?.counts.jobs ?? "?" })}
            </span>
          </div>
          {snapshot?.nodes
            .filter((n) => n.type !== "tool" && n.type !== "device")
            .slice(0, 3)
            .map((n) => (
              <div className={styles.summaryRow} key={n.id}>
                <span>{n.name}</span>
                <ActivityStatus node={n} stale={stale} />
              </div>
            ))}
          <div className={styles.summarySchedule}>
            <CalendarClock size={16} />
            <span>
              {nextTime
                ? t("workspace0034.nextAt", { time: nextTime })
                : t("workspace0034.noUpcoming")}
              <small>
                {t("workspace0034.scheduleSummary", {
                  schedules: scheduleCount,
                  reminders: reminderCount,
                })}
              </small>
            </span>
          </div>
        </>
      )}
      <Button type="primary" block onClick={details}>
        {t("workspace0034.openWorkbench")}
        <ArrowUpRight size={15} />
      </Button>
    </div>
  );
  return (
    <>
      <Popover open={summary && !open} trigger={[]} content={summaryContent}>
        <button
          ref={entry}
          className={`${styles.entry} ${compact ? styles.compact : ""}`}
          onPointerDown={(e) => {
            touch.current = e.pointerType === "touch";
          }}
          onClick={(e) => {
            if (e.detail === 0 || touch.current) {
              setSummary(true);
              return;
            }
            clearTimeout(clickTimer.current);
            if (e.detail === 1)
              clickTimer.current = setTimeout(() => setSummary(true), 250);
          }}
          onDoubleClick={details}
          onKeyDown={(e) => {
            if (e.key === "Enter" && e.altKey) {
              e.preventDefault();
              details();
            }
            if (e.key === "Escape") setSummary(false);
          }}
          aria-label={entryText}
          aria-expanded={summary || open}
        >
          {running.length && !stale ? (
            <LoaderCircle size={16} className={styles.running} />
          ) : (
            <Activity size={16} />
          )}
          <span>{entryText}</span>
        </button>
      </Popover>
      <Modal
        open={open}
        title={null}
        footer={null}
        closable={false}
        width="min(1240px, calc(100vw - 48px))"
        centered={!fullscreen}
        wrapClassName={styles.modalWrap}
        onCancel={close}
        className={styles.modal}
        classNames={{ content: styles.modalContent, body: styles.modalBody }}
        styles={{
          content: {
            padding: 0,
            overflow: "hidden",
            ...(fullscreen ? { borderRadius: 0 } : {}),
          },
          body: { padding: 0 },
        }}
      >
        <div className={styles.workbench}>
          <header className={styles.header}>
            <div>
              <h2>{t("workspace0034.workbench")}</h2>
              <span>{t("workspace0034.scopeCurrent")}</span>
            </div>
            <div className={styles.observation}>
              <span className={stale ? styles.staleDot : styles.currentDot} />
              {stale
                ? t("workspace0034.observationUnavailable")
                : snapshot
                ? t("workspace0034.observedAt", {
                    time: new Date(
                      snapshot.observed_at * 1000,
                    ).toLocaleTimeString(undefined, {
                      timeZone: timezone,
                      hour: "2-digit",
                      minute: "2-digit",
                    }),
                  })
                : t("workspace0034.loading")}
            </div>
            <Button
              type="text"
              aria-label={t("common.close")}
              icon={<X size={20} />}
              onClick={close}
            />
          </header>
          <div className={styles.frame}>
            <nav
              className={styles.navigation}
              aria-label={t("workspace0034.workbench")}
            >
              {[
                {
                  key: "live",
                  label: "liveScene",
                  icon: Activity,
                  count: snapshot ? (running.length ? "●" : "") : "?",
                },
                {
                  key: "schedules",
                  label: "schedules",
                  icon: CalendarClock,
                  count:
                    navSchedules.loading || navSchedules.error
                      ? "?"
                      : navSchedules.counts.schedules,
                },
                {
                  key: "reminders",
                  label: "reminders",
                  icon: Bell,
                  count:
                    navSchedules.loading || navSchedules.error
                      ? "?"
                      : navSchedules.counts.reminders,
                },
              ].map((item) => (
                <button
                  key={item.key}
                  aria-current={section === item.key ? "page" : undefined}
                  className={section === item.key ? styles.navSelected : ""}
                  onClick={() => {
                    setSection(item.key);
                    setScheduleScope("thread");
                    setSelected("");
                  }}
                >
                  <item.icon size={18} />
                  <span>{t(`workspace0034.${item.label}`)}</span>
                  <small>{item.count}</small>
                </button>
              ))}
            </nav>
            <main className={styles.main}>
              {section !== "live" ? (
                <ScheduleBrowser
                  key={section}
                  agentId={agentId}
                  threadId={threadId}
                  reminder={section === "reminders"}
                  onScopeChange={setScheduleScope}
                  onNavigate={() => {
                    setOpen(false);
                    setSummary(false);
                  }}
                />
              ) : (
                <>
                  <div className={styles.toolbar}>
                    <Segmented
                      value={filter}
                      onChange={(value) => setFilter(String(value))}
                      options={[
                        {
                          value: "all",
                          label: `${t("workspace0034.allActivities")} (${
                            nodes.length
                          })`,
                        },
                        {
                          value: "agents",
                          label: `${t("workspace0034.agents")} (${
                            nodes.filter((n) =>
                              ["subagent", "delegation"].includes(n.type),
                            ).length
                          })`,
                        },
                        {
                          value: "jobs",
                          label: `${t("workspace0034.background")} (${
                            nodes.filter((n) => n.type === "job").length
                          })`,
                        },
                      ]}
                    />
                    <Segmented
                      value={graph ? "graph" : "list"}
                      onChange={(value) => setView(String(value))}
                      options={[
                        { value: "graph", label: t("workspace0034.dag") },
                        { value: "list", label: t("workspace0034.runs") },
                      ]}
                    />
                  </div>
                  {(snapshot?.scope_truncated ||
                    snapshot?.active_scope_truncated) && (
                    <div className={styles.scopeNote}>
                      {t(
                        snapshot.active_scope_truncated
                          ? "workspace0034.activeWindow"
                          : "workspace0034.historyWindow",
                      )}
                    </div>
                  )}
                  {!plans && (
                    <div className={styles.scopeNote}>
                      {t("workspace0034.noExplicitDependencies")}
                    </div>
                  )}
                  {error && (
                    <Alert
                      type="warning"
                      message={t("workspace0034.observationUnavailable")}
                    />
                  )}
                  <div
                    className={`${styles.scene} ${
                      selectedNode ? styles.hasDetail : ""
                    }`}
                  >
                    <section className={styles.canvas}>
                      {!snapshot ? (
                        <Skeleton active paragraph={{ rows: 8 }} />
                      ) : graph ? (
                        <TaskActivityGraph
                          timezone={timezone}
                          snapshot={{
                            ...snapshot,
                            nodes: snapshot.nodes.filter(
                              (n) =>
                                n.type === "plan" ||
                                filter === "all" ||
                                (filter === "agents" &&
                                  ["subagent", "delegation"].includes(
                                    n.type,
                                  )) ||
                                (filter === "jobs" && n.type === "job"),
                            ),
                          }}
                          selected={selected}
                          onSelect={setSelected}
                          stale={stale}
                        />
                      ) : (
                        list
                      )}
                    </section>
                    {selectedNode && (
                      <aside className={styles.nodePanel}>
                        <Button
                          className={styles.back}
                          type="text"
                          icon={<ArrowLeft size={16} />}
                          onClick={() => setSelected("")}
                        >
                          {t("workspace0034.backToTasks")}
                        </Button>
                        <NodeDetail
                          key={`${agentId}:${threadId}:${selectedNode.id}`}
                          stale={stale}
                          node={selectedNode}
                          agentId={agentId}
                          threadId={threadId}
                        />
                      </aside>
                    )}
                  </div>
                </>
              )}
            </main>
          </div>
        </div>
      </Modal>
    </>
  );
}
