import FailureDiagnostics from "../../../components/FailureDiagnostics";
import ConversationOutline from "./ConversationOutline";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  App,
  Button,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Segmented,
  Select,
  Space,
  Spin,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { FileText, RefreshCw } from "lucide-react";
import { fileTreeIcon } from "../../../utils/fileTreeIcon";
import { useTranslation } from "react-i18next";
import { useServerTimezone } from "../../../hooks/useServerTimezone";
import {
  formatServerDateTime,
  formatServerYmd,
} from "../../../utils/formatMessageTime";
import { apiErrorMessage } from "../../../utils/apiError";
import {
  conversationMetadataApi as api,
  type BriefItem,
  type ConversationBrief,
  type ConversationDigest,
  type ConversationEventPage,
  type ConversationSource,
  type ConversationSourceRef,
  type MetadataJob,
} from "../../../api/modules/conversationMetadata";
import { emitSessionEvent, onSessionEvent } from "../hooks/chatStore";
import styles from "./ConversationOverview.module.less";
import { OPEN_TASK_ACTIVITY_EVENT } from "./TaskActivity";

export default function ConversationOverview({
  agentId,
  threadId,
  compact = false,
  onOpenArtifact,
}: {
  agentId: string;
  threadId: string;
  compact?: boolean;
  onOpenArtifact?: (path: string, agentId?: string | null) => void;
}) {
  const { t, i18n } = useTranslation();
  const { message, modal } = App.useApp();
  const timezone = useServerTimezone();
  const [open, setOpen] = useState(false);
  const [brief, setBrief] = useState<ConversationBrief | null>(null);
  const needsLanguageRefresh =
    (i18n?.resolvedLanguage ?? i18n?.language ?? "").startsWith("zh") &&
    !!brief?.provenance.generated_at &&
    !brief.manual_overrides.objective &&
    /[a-zA-Z]{3}/.test(brief.overview.objective) &&
    !/[\u3400-\u9fff]/.test(brief.overview.objective);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("overview");
  const [events, setEvents] = useState<ConversationEventPage | null>(null);
  const [period, setPeriod] = useState("today");
  const today = formatServerYmd(Date.now(), timezone);
  const [from, setFrom] = useState(today);
  const [to, setTo] = useState(today);
  const [windowValue, setWindowValue] = useState("today");
  const [digest, setDigest] = useState<ConversationDigest | null>(null);
  const [job, setJob] = useState<MetadataJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [source, setSource] = useState<ConversationSource | null>(null);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editingRevision, setEditingRevision] = useState(0);
  const [editForm] = Form.useForm();
  const identity = `${agentId}/${threadId}`;
  const identityRef = useRef(identity);
  identityRef.current = identity;
  const requestSeq = useRef(0);
  const eventRequestSeq = useRef(0);
  const sourceRequestSeq = useRef(0);
  const load = useCallback(async () => {
    const seq = ++requestSeq.current;
    try {
      const value = await api.brief(agentId, threadId);
      if (identityRef.current === identity && seq === requestSeq.current) {
        setBrief(value);
        setError("");
      }
    } catch (err) {
      if (identityRef.current === identity && seq === requestSeq.current)
        setError(
          apiErrorMessage(err, t("conversationMetadata.generationFailed")),
        );
    }
  }, [agentId, threadId, identity, t]);
  const loadEvents = useCallback(
    async (cursor?: string) => {
      const seq = ++eventRequestSeq.current;
      const value = await api.events(agentId, threadId, windowValue, cursor);
      if (identityRef.current !== identity || seq !== eventRequestSeq.current)
        return;
      setEvents((old) =>
        cursor && old
          ? {
              ...value,
              events: [
                ...old.events,
                ...value.events.filter(
                  (row) => !old.events.some((e) => e.event_id === row.event_id),
                ),
              ],
            }
          : value,
      );
    },
    [agentId, threadId, windowValue, identity],
  );
  useEffect(() => {
    setOpen(false);
    setBrief(null);
    setEvents(null);
    setDigest(null);
    setJob(null);
    setSourceOpen(false);
    setEditing(false);
    setError("");
    setBusy(false);
    setSourceLoading(false);
  }, [identity]);
  useEffect(() => {
    if (!open) return;
    const requestGeneration = requestSeq;
    void load();
    const timer = window.setInterval(() => void load(), 3000);
    const off = onSessionEvent((event) => {
      if (event.sessionId === threadId) void load();
    });
    return () => {
      window.clearInterval(timer);
      off();
      requestGeneration.current++;
    };
  }, [open, load, threadId]);
  useEffect(() => {
    if (!open || tab !== "timeline") return;
    setEvents(null);
    setDigest(null);
    setJob((value) => (value?.kind === "digest" ? null : value));
    void loadEvents().catch((err) =>
      message.error(
        apiErrorMessage(err, t("conversationMetadata.generationFailed")),
      ),
    );
  }, [open, tab, loadEvents, message, t]);
  useEffect(() => {
    if (!job || !["queued", "retry", "running"].includes(job.status)) return;
    let cancelled = false;
    let inFlight = false;
    const timer = window.setInterval(() => {
      if (inFlight) return;
      inFlight = true;
      void api
        .job(agentId, threadId, job.job_id)
        .then(async (value) => {
          if (cancelled || identityRef.current !== identity) return;
          if (value.status === "cancelled") {
            setJob(value);
            return;
          }
          if (value.status === "failed") {
            setJob(value);
            message.error(
              t(
                `conversationMetadata.errors.${value.error_code}`,
                t("conversationMetadata.generationFailed"),
              ),
            );
          } else if (value.status === "ready") {
            if (value.result.suggested_title) {
              modal.confirm({
                title: t("conversationMetadata.titleSuggestion"),
                content: value.result.suggested_title,
                okText: t("conversationMetadata.applyTitle"),
                onOk: async () => {
                  if (identityRef.current !== identity) return;
                  await api.titleAction(agentId, threadId, {
                    action: "apply",
                    expected_revision: value.result.title_revision ?? 0,
                    title: value.result.suggested_title,
                  });
                  await load();
                  emitSessionEvent({
                    kind: "sessionsChanged",
                    sessionId: threadId,
                    agentId,
                  });
                },
              });
            }
            if (value.result.digest_id) {
              const result = await api.getDigest(
                agentId,
                threadId,
                value.result.digest_id,
              );
              if (!cancelled && identityRef.current === identity)
                setDigest(result);
            }
            if (cancelled || identityRef.current !== identity) return;
            setJob(value);
            await load();
          } else setJob(value);
        })
        .catch((err) => {
          if (!cancelled)
            message.error(
              apiErrorMessage(err, t("conversationMetadata.generationFailed")),
            );
        })
        .finally(() => {
          inFlight = false;
        });
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [job, agentId, threadId, identity, load, message, modal, t]);
  const generating = Boolean(
    job && ["queued", "retry", "running"].includes(job.status),
  );
  const applySuggestedTitle = async () => {
    if (!brief?.suggested_title) return;
    setBusy(true);
    try {
      const value = await api.titleAction(agentId, threadId, {
        action: "apply",
        expected_revision: brief.title_revision,
        title: brief.suggested_title,
      });
      if (identityRef.current !== identity) return;
      setBrief(value);
      emitSessionEvent({
        kind: "sessionsChanged",
        sessionId: threadId,
        agentId,
      });
    } catch (err) {
      message.error(
        apiErrorMessage(err, t("conversationMetadata.generationFailed")),
      );
    } finally {
      if (identityRef.current === identity) setBusy(false);
    }
  };
  const generate = async (kind: "title" | "brief") => {
    setBusy(true);
    try {
      const value = await api.generate(agentId, threadId, kind);
      if (identityRef.current === identity) setJob(value);
    } catch (err) {
      message.error(
        apiErrorMessage(err, t("conversationMetadata.generationFailed")),
      );
    } finally {
      if (identityRef.current === identity) setBusy(false);
    }
  };
  const patch = async (
    changes: Record<string, unknown>,
    revision = brief?.revision,
  ) => {
    if (revision === undefined) return;
    setBusy(true);
    try {
      const result = await api.patch(agentId, threadId, {
        expected_revision: revision,
        ...changes,
      });
      if (identityRef.current !== identity) return;
      setBrief(result);
      setEditing(false);
      emitSessionEvent({
        kind: "sessionsChanged",
        sessionId: threadId,
        agentId,
      });
    } catch (err) {
      message.error(
        apiErrorMessage(err, t("conversationMetadata.generationFailed")),
      );
    } finally {
      setBusy(false);
    }
  };
  const readSource = async (ref: ConversationSourceRef) => {
    const seq = ++sourceRequestSeq.current;
    setSourceOpen(true);
    setSource(null);
    setSourceLoading(true);
    try {
      const value = await api.source(agentId, threadId, ref);
      if (identityRef.current === identity && seq === sourceRequestSeq.current)
        setSource(value);
    } catch (err) {
      message.error(
        apiErrorMessage(err, t("conversationMetadata.generationFailed")),
      );
    } finally {
      if (identityRef.current === identity && seq === sourceRequestSeq.current)
        setSourceLoading(false);
    }
  };
  const references = (refs: ConversationSourceRef[]) =>
    refs.map((ref, index) => (
      <Button
        type="default"
        size="small"
        className={styles.sourceChip}
        key={`${ref.kind}:${ref.id}`}
        onClick={() => void readSource(ref)}
      >
        {t("conversationMetadata.source")}
        {refs.length > 1 ? ` ${index + 1}` : ""}
      </Button>
    ));
  const items = (label: string, values: BriefItem[]) =>
    values.length > 0 && (
      <section className={styles.section}>
        <h3>{t(`conversationMetadata.${label}`)}</h3>
        <ul className={styles.list}>
          {values.map((item, index) => (
            <li key={index}>
              {item.text}
              {references(item.source_refs)}
            </li>
          ))}
        </ul>
      </section>
    );
  const getDigest = async () => {
    setBusy(true);
    try {
      const value = await api.digest(agentId, threadId, windowValue);
      if (identityRef.current !== identity) return;
      if ("job_id" in value) setJob(value);
      else setDigest(value);
    } catch (err) {
      message.error(
        apiErrorMessage(err, t("conversationMetadata.generationFailed")),
      );
    } finally {
      setBusy(false);
    }
  };
  const stamp = (value: number) => formatServerDateTime(value, timezone);
  return (
    <>
      <Button
        type="text"
        className={styles.trigger}
        icon={<FileText size={16} />}
        onClick={() => setOpen(true)}
        aria-label={t("conversationMetadata.overviewTitle")}
      >
        {!compact && t("conversationMetadata.overviewTitle")}
      </Button>
      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title={t("conversationMetadata.overviewTitle")}
        width="min(600px, 100vw)"
        destroyOnClose
      >
        {error && (
          <Alert
            type="error"
            message={error}
            showIcon
            action={
              <Button onClick={() => void load()}>{t("common.retry")}</Button>
            }
          />
        )}
        {!brief && !error && <Spin />}
        {brief && (
          <div className={styles.content}>
            <Space wrap>
              <Typography.Title level={4} className={styles.title}>
                {brief.title || t("conversationMetadata.untitled")}
              </Typography.Title>
              <Tag>
                {t(
                  `conversationMetadata.states.${brief.progress.display_state}`,
                  brief.progress.display_state,
                )}
              </Tag>
              <Tag>
                {t("conversationMetadata.executionState", {
                  state: t(
                    `conversationMetadata.states.${brief.progress.execution_state}`,
                    brief.progress.execution_state,
                  ),
                })}
              </Tag>
            </Space>
            <div className={styles.secondary}>
              {t(
                `conversationMetadata.titleSources.${brief.title_source}`,
                brief.title_source,
              )}
            </div>
            <p>
              {brief.overview.one_liner || t("conversationMetadata.noBrief")}
            </p>
            <Space wrap className={styles.actions}>
              <Button
                size="small"
                onClick={() => {
                  setOpen(false);
                  window.dispatchEvent(
                    new CustomEvent(OPEN_TASK_ACTIVITY_EVENT, {
                      detail: { agentId, threadId },
                    }),
                  );
                }}
              >
                {t("conversationMetadata.openActivity")}
              </Button>
              <Button
                size="small"
                icon={<RefreshCw size={13} />}
                loading={busy}
                disabled={generating}
                onClick={() => void generate("brief")}
              >
                {t("conversationMetadata.regenerate")}
              </Button>
              <Button
                size="small"
                disabled={busy || generating}
                onClick={() => void generate("title")}
              >
                {t("conversationMetadata.regenerateTitle")}
              </Button>
              {brief.title_source !== "fallback" && (
                <Button
                  size="small"
                  onClick={() => {
                    setBusy(true);
                    void api
                      .titleAction(agentId, threadId, {
                        action: "restore",
                        expected_revision: brief.title_revision,
                      })
                      .then((value) => {
                        if (identityRef.current === identity) setBrief(value);
                      })
                      .catch((err) =>
                        message.error(
                          apiErrorMessage(
                            err,
                            t("conversationMetadata.generationFailed"),
                          ),
                        ),
                      )
                      .finally(() => {
                        if (identityRef.current === identity) setBusy(false);
                      });
                  }}
                  disabled={busy || generating}
                >
                  {t("conversationMetadata.restoreTitle")}
                </Button>
              )}
            </Space>
            {brief.suggested_title && brief.suggested_title !== brief.title && (
              <Alert
                className={styles.notice}
                type="info"
                message={t("conversationMetadata.titleSuggestion")}
                description={brief.suggested_title}
                action={
                  <Button
                    size="small"
                    disabled={busy}
                    onClick={() => void applySuggestedTitle()}
                  >
                    {t("conversationMetadata.applyTitle")}
                  </Button>
                }
              />
            )}
            {generating && (
              <Alert
                type="info"
                className={styles.notice}
                message={t("conversationMetadata.generating")}
                action={
                  <Button
                    onClick={async () => {
                      if (job)
                        setJob(
                          await api.cancelJob(agentId, threadId, job.job_id),
                        );
                    }}
                  >
                    {t("conversationMetadata.stopOrganizing")}
                  </Button>
                }
                showIcon
              />
            )}
            {brief.provenance.last_error && (
              <Alert
                type="warning"
                className={styles.notice}
                message={t(
                  `conversationMetadata.errors.${brief.provenance.last_error}`,
                  t("conversationMetadata.generationFailed"),
                )}
                action={
                  <FailureDiagnostics
                    summary={t(
                      `conversationMetadata.errors.${brief.provenance.last_error}`,
                      t("conversationMetadata.generationFailed"),
                    )}
                    value={{
                      ...(job?.result.diagnostic ??
                        brief.provenance.diagnostic),
                      code: brief.provenance.last_error,
                    }}
                  />
                }
                showIcon
              />
            )}
            {needsLanguageRefresh && (
              <Alert
                type="info"
                className={styles.notice}
                message={t("conversationMetadata.languageMismatch")}
                action={
                  <Button
                    size="small"
                    disabled={busy || generating}
                    onClick={() => void generate("brief")}
                  >
                    {t("conversationMetadata.refreshLanguage")}
                  </Button>
                }
              />
            )}
            <Tabs
              activeKey={tab}
              onChange={setTab}
              items={[
                {
                  key: "outline",
                  label: t("conversationMetadata.outline"),
                  children: (
                    <ConversationOutline
                      brief={brief}
                      references={references}
                    />
                  ),
                },
                {
                  key: "overview",
                  label: t("conversationMetadata.overview"),
                  children: (
                    <>
                      <section className={styles.overviewSummary}>
                        <div className={styles.objectiveCard}>
                          <h3>{t("conversationMetadata.objective")}</h3>
                          <p>
                            {brief.overview.objective ||
                              t("conversationMetadata.notRecorded")}
                          </p>
                          {brief.overview.scope && (
                            <div className={styles.scopeText}>
                              <span>{t("conversationMetadata.scope")}</span>
                              <p>{brief.overview.scope}</p>
                            </div>
                          )}
                        </div>
                        <div className={styles.progressCards}>
                          <div>
                            <span>{t("conversationMetadata.stage")}</span>
                            <strong>
                              {brief.progress.stage ||
                                t("conversationMetadata.notRecorded")}
                            </strong>
                          </div>
                          <div>
                            <span>{t("conversationMetadata.plan")}</span>
                            <strong>
                              {brief.progress.plan_total
                                ? t("conversationMetadata.reportedPlan", {
                                    completed:
                                      brief.progress.reported_plan_completed,
                                    total: brief.progress.plan_total,
                                  })
                                : t("conversationMetadata.noPlan")}
                            </strong>
                          </div>
                        </div>
                      </section>
                      {items("constraints", brief.overview.constraints)}
                      {items("completed", brief.progress.completed)}
                      {items("inProgress", brief.progress.in_progress)}
                      {items("remaining", brief.progress.remaining)}
                      {items("blockers", brief.progress.blockers)}
                      {items("nextActions", brief.progress.next_actions)}
                      <section className={styles.section}>
                        <h3>{t("conversationMetadata.verification")}</h3>
                        {brief.progress.truncated && (
                          <Tag>{t("conversationMetadata.partial")}</Tag>
                        )}
                        <p>
                          {t("conversationMetadata.verificationCounts", {
                            backed: brief.progress.verification_passed || 0,
                            reported: brief.progress.verification_reported || 0,
                          })}
                        </p>
                        {references(
                          (brief.progress.verification || []).flatMap(
                            (check) => check.source_refs,
                          ),
                        )}
                      </section>
                      {brief.manual_overrides.note && (
                        <section className={styles.section}>
                          <h3>{t("conversationMetadata.note")}</h3>
                          <p>{brief.manual_overrides.note}</p>
                        </section>
                      )}
                      <Alert
                        className={styles.notice}
                        type="info"
                        message={t("conversationMetadata.progressCaution")}
                      />
                      <Space wrap>
                        <Button
                          disabled={busy}
                          onClick={() => {
                            setEditingRevision(brief.revision);
                            editForm.setFieldsValue({
                              ...brief.overview,
                              note: brief.manual_overrides.note || "",
                            });
                            setEditing(true);
                          }}
                        >
                          {t("conversationMetadata.correct")}
                        </Button>
                        <Select
                          aria-label={t("conversationMetadata.workState")}
                          value={
                            brief.progress.work_state === "unknown"
                              ? undefined
                              : brief.progress.work_state
                          }
                          placeholder={t("conversationMetadata.workState")}
                          onChange={(value) =>
                            void patch({ work_state: value })
                          }
                          disabled={busy}
                          options={[
                            "in_progress",
                            "blocked",
                            "ready_for_review",
                            "completed",
                            "cancelled",
                          ].map((value) => ({
                            value,
                            label: t(`conversationMetadata.states.${value}`),
                          }))}
                        />
                        {Object.keys(brief.manual_overrides).some((key) =>
                          ["objective", "scope", "note"].includes(key),
                        ) && (
                          <Button
                            onClick={() =>
                              void patch({
                                objective: null,
                                scope: null,
                                note: null,
                              })
                            }
                          >
                            {t("conversationMetadata.restoreBrief")}
                          </Button>
                        )}
                      </Space>
                      {brief.progress.acceptance && (
                        <p className={styles.secondary}>
                          {t("conversationMetadata.acceptedAt", {
                            time: stamp(brief.progress.acceptance.at),
                          })}
                        </p>
                      )}
                    </>
                  ),
                },
                {
                  key: "timeline",
                  label: t("conversationMetadata.timeline"),
                  children: (
                    <>
                      <Segmented
                        block
                        value={period}
                        onChange={(value) => {
                          setPeriod(String(value));
                          if (value !== "custom") setWindowValue(String(value));
                        }}
                        options={[
                          {
                            value: "today",
                            label: t("conversationMetadata.today"),
                          },
                          {
                            value: "last_7d",
                            label: t("conversationMetadata.week"),
                          },
                          {
                            value: "custom",
                            label: t("conversationMetadata.custom"),
                          },
                        ]}
                      />
                      {period === "custom" && (
                        <div className={styles.dates}>
                          <label>
                            {t("conversationMetadata.from")}
                            <Input
                              type="date"
                              value={from}
                              onChange={(e) => setFrom(e.target.value)}
                            />
                          </label>
                          <label>
                            {t("conversationMetadata.to")}
                            <Input
                              type="date"
                              value={to}
                              onChange={(e) => setTo(e.target.value)}
                            />
                          </label>
                          <Button
                            onClick={() => {
                              if (!from || !to || from > to) {
                                message.error(
                                  t("conversationMetadata.invalidRange"),
                                );
                                return;
                              }
                              setWindowValue(`range:${from}:${to}`);
                            }}
                          >
                            {t("conversationMetadata.view")}
                          </Button>
                        </div>
                      )}
                      {events && (
                        <p className={styles.secondary}>
                          {stamp(events.from_ts)} — {stamp(events.to_ts)} ·{" "}
                          {events.timezone}
                        </p>
                      )}
                      <Button
                        onClick={() => void getDigest()}
                        loading={busy}
                        disabled={generating}
                      >
                        {t("conversationMetadata.generateDigest")}
                      </Button>
                      {digest && (
                        <section className={styles.section}>
                          <h3>{t("conversationMetadata.periodSummary")}</h3>
                          <p className={styles.preserve}>
                            {digest.summary ||
                              t("conversationMetadata.noEvents")}
                          </p>
                          {(!digest.coverage.complete ||
                            digest.freshness !== "current") && (
                            <Tag>{t("conversationMetadata.partial")}</Tag>
                          )}
                        </section>
                      )}
                      {!events ? (
                        <Spin />
                      ) : events.events.length === 0 ? (
                        <Empty
                          description={t("conversationMetadata.noEvents")}
                        />
                      ) : (
                        <div className={styles.events}>
                          {events.events.map((event) => (
                            <article
                              key={event.event_id}
                              className={styles.event}
                            >
                              <div className={styles.secondary}>
                                {stamp(event.occurred_at)} ·{" "}
                                {t(
                                  `conversationMetadata.eventKinds.${event.kind}`,
                                  {
                                    defaultValue: event.kind,
                                    title:
                                      event.details.source_title ||
                                      t("conversationMetadata.untitled"),
                                  },
                                )}
                              </div>
                              <p>
                                {event.text ||
                                  t(
                                    `conversationMetadata.eventKinds.${event.kind}`,
                                    {
                                      defaultValue: event.kind,
                                      title:
                                        event.details.source_title ||
                                        t("conversationMetadata.untitled"),
                                    },
                                  )}
                              </p>
                              {references(
                                event.source_refs.length
                                  ? event.source_refs
                                  : [{ kind: "event", id: event.event_id }],
                              )}
                            </article>
                          ))}
                          {events.next_cursor && (
                            <Button
                              onClick={() =>
                                void loadEvents(
                                  events.next_cursor || undefined,
                                ).catch((err) =>
                                  message.error(
                                    apiErrorMessage(
                                      err,
                                      t(
                                        "conversationMetadata.generationFailed",
                                      ),
                                    ),
                                  ),
                                )
                              }
                            >
                              {t("conversationMetadata.loadMore")}
                            </Button>
                          )}
                        </div>
                      )}
                    </>
                  ),
                },
                {
                  key: "decisions",
                  label: t("conversationMetadata.decisionsAndResults"),
                  children: (
                    <>
                      {items("decisions", brief.decisions)}
                      {items("findings", brief.findings)}
                      <section className={styles.section}>
                        <h3>{t("conversationMetadata.artifacts")}</h3>
                        {brief.artifact_refs.length ? (
                          <ul className={styles.artifactGrid}>
                            {brief.artifact_refs.map((a) => (
                              <li
                                key={`${a.agent_id}:${a.path}`}
                                className={styles.path}
                              >
                                <Button
                                  type="default"
                                  title={a.path}
                                  aria-label={a.path}
                                  className={styles.artifact}
                                  onClick={() => {
                                    setOpen(false);
                                    onOpenArtifact?.(a.path, a.agent_id);
                                  }}
                                  disabled={!onOpenArtifact}
                                >
                                  {(() => {
                                    const name =
                                      a.path.split(/[\\/]/).pop() || a.path;
                                    const ext =
                                      name.split(".").pop()?.toLowerCase() ||
                                      "";
                                    return (
                                      <>
                                        {fileTreeIcon(a.path, 30)}
                                        <strong>{name}</strong>
                                        <small>
                                          {ext.toUpperCase() || "FILE"}
                                        </small>
                                      </>
                                    );
                                  })()}
                                </Button>
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <Empty
                            description={t("conversationMetadata.noArtifacts")}
                          />
                        )}
                      </section>
                    </>
                  ),
                },
              ]}
            />
            <div className={styles.provenance}>
              <Tag>
                {t(
                  `conversationMetadata.freshness.${brief.provenance.freshness}`,
                  brief.provenance.freshness,
                )}
              </Tag>
              <span>
                {brief.provenance.generated_at
                  ? stamp(brief.provenance.generated_at)
                  : t("conversationMetadata.notGenerated")}
              </span>
              <div>
                {t("conversationMetadata.coverage", {
                  seq: brief.provenance.coverage.message_seq,
                  archive: brief.provenance.coverage.archive_seq,
                })}
                {brief.provenance.effective_model_ref
                  ? ` · ${brief.provenance.effective_model_ref}`
                  : ""}
              </div>
            </div>
          </div>
        )}
      </Drawer>
      <Modal
        open={editing}
        title={t("conversationMetadata.correct")}
        onCancel={() => setEditing(false)}
        footer={null}
      >
        <Form
          form={editForm}
          layout="vertical"
          onFinish={(values) => void patch(values, editingRevision)}
        >
          <Form.Item
            name="objective"
            label={t("conversationMetadata.objective")}
          >
            <Input.TextArea
              maxLength={1000}
              autoSize={{ minRows: 2, maxRows: 5 }}
            />
          </Form.Item>
          <Form.Item name="scope" label={t("conversationMetadata.scope")}>
            <Input.TextArea
              maxLength={1000}
              autoSize={{ minRows: 2, maxRows: 5 }}
            />
          </Form.Item>
          <Form.Item name="note" label={t("conversationMetadata.note")}>
            <Input.TextArea
              maxLength={3000}
              autoSize={{ minRows: 2, maxRows: 6 }}
            />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={busy}>
            {t("common.save")}
          </Button>
        </Form>
      </Modal>
      <Modal
        open={sourceOpen}
        title={t("conversationMetadata.source")}
        onCancel={() => setSourceOpen(false)}
        footer={null}
      >
        {sourceLoading ? (
          <Spin />
        ) : source ? (
          <>
            <p className={styles.preserve}>{source.text}</p>
            {source.details.partial === true && (
              <Alert
                type="info"
                message={t("conversationMetadata.sourceExcerpt")}
              />
            )}
            {typeof source.details.status === "string" && (
              <Tag>
                {t(
                  `conversationMetadata.states.${source.details.status}`,
                  source.details.status,
                )}
              </Tag>
            )}
            {typeof source.details.occurred_at === "number" && (
              <p className={styles.secondary}>
                {stamp(source.details.occurred_at)}
              </p>
            )}
            {Array.isArray(source.details.tasks) && (
              <ul className={styles.list}>
                {source.details.tasks.map(
                  (task, index) =>
                    typeof task === "object" &&
                    task !== null && (
                      <li key={index}>
                        {String(task.title || task.text || task.content || "")}{" "}
                        ·{" "}
                        {t(
                          `workspace0034.status.${task.status}`,
                          String(task.status || ""),
                        )}
                      </li>
                    ),
                )}
              </ul>
            )}
            {source.details.changes &&
              typeof source.details.changes === "object" && (
                <Descriptions
                  column={1}
                  size="small"
                  items={Object.entries(source.details.changes)
                    .filter(([key]) =>
                      ["objective", "scope", "note", "work_state"].includes(
                        key,
                      ),
                    )
                    .map(([key, value]) => ({
                      key,
                      label: t(
                        `conversationMetadata.${
                          key === "work_state" ? "workState" : key
                        }`,
                      ),
                      children:
                        value == null
                          ? t("conversationMetadata.restoreBrief")
                          : key === "work_state"
                          ? t(
                              `conversationMetadata.states.${value}`,
                              String(value),
                            )
                          : String(value),
                    }))}
                />
              )}
            {Array.isArray(source.details.source_refs) &&
              references(
                source.details.source_refs.filter(
                  (ref): ref is ConversationSourceRef =>
                    Boolean(
                      ref &&
                        typeof ref === "object" &&
                        typeof ref.kind === "string" &&
                        typeof ref.id === "string",
                    ),
                ),
              )}
          </>
        ) : (
          <Empty description={t("conversationMetadata.sourceUnavailable")} />
        )}
      </Modal>
    </>
  );
}
