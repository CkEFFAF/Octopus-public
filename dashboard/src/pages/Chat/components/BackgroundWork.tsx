import { useRef, useState } from "react";
import { Alert, Button, Drawer, Input, Segmented, Skeleton, Tag } from "antd";
import { Layers, Plus, RefreshCw, ArrowUpRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import {
  workItemsApi,
  type WorkItemStatus,
} from "../../../api/modules/workItems";
import { apiErrorMessage } from "../../../utils/apiError";
import { useServerTimezone } from "../../../hooks/useServerTimezone";
import { formatServerDateTime } from "../../../utils/formatMessageTime";
import { useWorkItems, WORK_ITEMS_CHANGED_EVENT } from "../hooks/useWorkItems";
import {
  executionScope,
  LOCAL_TARGET,
  useExecutionSelection,
  useExecutionSelectionStatus,
} from "../hooks/deviceTarget";
import styles from "./BackgroundWork.module.less";

const terminal = new Set<WorkItemStatus>(["completed", "failed", "cancelled"]);

export default function BackgroundWork({
  agentId,
  threadId,
}: {
  agentId: string;
  threadId: string;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const timeZone = useServerTimezone();
  const [open, setOpen] = useState(false);
  const [all, setAll] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [instructions, setInstructions] = useState("");
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const commandIds = useRef(new Map<string, string>());
  const scope = executionScope(agentId, threadId);
  const execution = useExecutionSelection(scope);
  const selectionStatus = useExecutionSelectionStatus(scope);
  const { items, detail, error, hasMore, refresh } = useWorkItems(
    threadId,
    all,
    open && !creating ? selected : null,
  );
  const active = items.filter(
    (item) => item.origin_thread_id === threadId && !terminal.has(item.status),
  );
  const canCreate =
    selectionStatus === "ready" &&
    Boolean(execution.deviceId) &&
    execution.workMode === "agentic";
  const status = (item: {
    status: WorkItemStatus;
    cancel_requested: boolean | number;
  }) =>
    t(
      `chat.workItems.status.${
        item.cancel_requested && !terminal.has(item.status)
          ? "cancelling"
          : item.status
      }`,
    );
  const changed = () =>
    window.dispatchEvent(new Event(WORK_ITEMS_CHANGED_EVENT));
  async function mutate(
    key: string,
    operation: (commandId: string) => Promise<unknown>,
    success: () => void,
  ) {
    if (busy) return;
    const id = commandIds.current.get(key) ?? crypto.randomUUID();
    commandIds.current.set(key, id);
    setBusy(true);
    setActionError("");
    try {
      await operation(id);
      commandIds.current.delete(key);
      success();
      changed();
    } catch (err) {
      setActionError(
        apiErrorMessage(err, t("chat.workItems.requestFailed"), t),
      );
    } finally {
      setBusy(false);
    }
  }
  function create() {
    if (!canCreate || !title.trim() || !instructions.trim()) return;
    const body = {
      agent_id: agentId,
      origin_thread_id: threadId,
      title: title.trim(),
      instructions: instructions.trim(),
      execution: {
        target_kind:
          execution.deviceId === LOCAL_TARGET
            ? ("local" as const)
            : ("device" as const),
        device_id:
          execution.deviceId === LOCAL_TARGET ? null : execution.deviceId,
        working_dir: execution.workingDir || null,
      },
    };
    void mutate(
      JSON.stringify(body),
      async (id) => {
        const result = await workItemsApi.create(body, id);
        setSelected(result.task_id);
      },
      () => {
        setCreating(false);
        setTitle("");
        setInstructions("");
      },
    );
  }
  function choose(id: string) {
    if (busy) return;
    setSelected(id);
    setCreating(false);
    setInput("");
    setActionError("");
    setOpen(true);
  }
  return (
    <div className={styles.backgroundWork}>
      <div className={styles.toolbar}>
        <Button
          type="text"
          size="small"
          icon={<Layers size={15} />}
          onClick={() => {
            setOpen(true);
            setCreating(false);
          }}
        >
          {t("chat.workItems.title")}
          {active.length ? ` (${active.length})` : ""}
        </Button>
        <Button
          type="text"
          size="small"
          icon={<Plus size={14} />}
          onClick={() => {
            setOpen(true);
            setCreating(true);
            setActionError("");
          }}
        >
          {t("chat.workItems.new")}
        </Button>
      </div>
      {active.slice(0, 3).map((item) => (
        <button
          type="button"
          className={styles.summary}
          key={item.task_id}
          onClick={() => choose(item.task_id)}
        >
          <span>{item.title}</span>
          <Tag color={item.status === "running" ? "processing" : "default"}>
            {status(item)}
          </Tag>
        </button>
      ))}
      {error && !open && (
        <span role="status" className={styles.stale}>
          {t("chat.workItems.stale")}
        </span>
      )}
      <Drawer
        title={t("chat.workItems.title")}
        open={open}
        width="min(760px, 100vw)"
        onClose={() => setOpen(false)}
      >
        <p className={styles.hint}>{t("chat.workItems.hint")}</p>
        {error && (
          <Alert
            type="warning"
            showIcon
            message={t("chat.workItems.stale")}
            action={
              <Button
                size="small"
                onClick={() => {
                  void refresh();
                  changed();
                }}
              >
                {t("common.retry")}
              </Button>
            }
          />
        )}
        {actionError && <Alert type="error" showIcon message={actionError} />}
        <div className={styles.drawerToolbar}>
          <Segmented
            disabled={busy}
            value={all ? "all" : "thread"}
            options={[
              { label: t("chat.workItems.thisChat"), value: "thread" },
              { label: t("chat.workItems.allChats"), value: "all" },
            ]}
            onChange={(value) => {
              setAll(value === "all");
              setSelected(null);
            }}
          />
          <Button
            type="text"
            icon={<RefreshCw size={14} />}
            aria-label={t("common.refresh")}
            onClick={() => {
              void refresh();
              changed();
            }}
          />
          <Button icon={<Plus size={14} />} onClick={() => setCreating(true)}>
            {t("chat.workItems.new")}
          </Button>
        </div>
        <div className={styles.layout}>
          <nav aria-label={t("chat.workItems.list")} className={styles.list}>
            {!items.length && <p>{t("chat.workItems.empty")}</p>}
            {items.map((item) => (
              <button
                type="button"
                key={item.task_id}
                aria-pressed={!creating && selected === item.task_id}
                onClick={() => choose(item.task_id)}
              >
                <strong>{item.title}</strong>
                <span>{status(item)}</span>
              </button>
            ))}
            {hasMore && <p>{t("chat.workItems.recentOnly")}</p>}
          </nav>
          <section className={styles.detail}>
            {creating ? (
              <>
                <h3>{t("chat.workItems.new")}</h3>
                <label>
                  {t("chat.workItems.taskTitle")}
                  <Input
                    disabled={busy}
                    value={title}
                    maxLength={200}
                    onChange={(event) => setTitle(event.target.value)}
                  />
                </label>
                <label>
                  {t("chat.workItems.instructions")}
                  <Input.TextArea
                    disabled={busy}
                    value={instructions}
                    rows={5}
                    maxLength={100000}
                    onChange={(event) => setInstructions(event.target.value)}
                  />
                </label>
                <p className={styles.hint}>
                  {t(
                    canCreate
                      ? "chat.workItems.executionHint"
                      : "chat.workItems.selectExecution",
                  )}
                </p>
                {execution.workingDir && (
                  <code className={styles.directory}>
                    {execution.workingDir}
                  </code>
                )}
                <Button
                  type="primary"
                  loading={busy}
                  disabled={!canCreate || !title.trim() || !instructions.trim()}
                  onClick={create}
                >
                  {t("chat.workItems.start")}
                </Button>
              </>
            ) : selected && !detail ? (
              <Skeleton active />
            ) : detail ? (
              <>
                <h3>{detail.title}</h3>
                <Tag>{status(detail)}</Tag>
                <p className={styles.instructions}>{detail.instructions}</p>
                <dl className={styles.progress}>
                  <dt>{t("chat.workItems.stage")}</dt>
                  <dd>
                    {detail.progress.phase
                      ? t(`chat.steer.phase.${detail.progress.phase}`, {
                          defaultValue: t("chat.flow.working"),
                        })
                      : t("chat.workItems.noProgress")}
                  </dd>
                  <dt>{t("chat.workItems.tools")}</dt>
                  <dd>
                    {detail.progress.active_tools.length
                      ? detail.progress.active_tools
                          .map((name) =>
                            t(`tools.${name}`, { defaultValue: name }),
                          )
                          .join(", ")
                      : t("chat.workItems.noTools")}
                  </dd>
                  <dt>{t("chat.workItems.updated")}</dt>
                  <dd>
                    {detail.progress.last_event_at
                      ? formatServerDateTime(
                          detail.progress.last_event_at,
                          timeZone,
                        )
                      : t("chat.workItems.noProgress")}
                  </dd>
                </dl>
                {(detail.progress.block_reason ||
                  detail.progress.needs_approval ||
                  detail.progress.needs_credential ||
                  detail.progress.permission_denied) && (
                  <Alert
                    type="warning"
                    showIcon
                    message={t(
                      detail.progress.needs_approval
                        ? "chat.workItems.needsApproval"
                        : detail.progress.needs_credential
                        ? "chat.workItems.needsCredential"
                        : detail.progress.permission_denied
                        ? "chat.workItems.permissionDenied"
                        : "chat.workItems.blocked",
                    )}
                  />
                )}
                {detail.origin_thread_missing ? (
                  <Alert
                    type="warning"
                    message={t("chat.workItems.originMissing")}
                  />
                ) : (
                  detail.origin_thread_id && (
                    <Button
                      type="link"
                      icon={<ArrowUpRight size={14} />}
                      onClick={() => {
                        setOpen(false);
                        navigate(
                          `/chat/${encodeURIComponent(
                            detail.agent_id,
                          )}/${encodeURIComponent(detail.origin_thread_id!)}`,
                        );
                      }}
                    >
                      {t("chat.workItems.openOrigin")}
                    </Button>
                  )
                )}
                {!terminal.has(detail.status) && (
                  <>
                    <label>
                      {t("chat.workItems.addRequirements")}
                      <Input.TextArea
                        disabled={busy}
                        value={input}
                        rows={3}
                        maxLength={50000}
                        onChange={(event) => setInput(event.target.value)}
                      />
                    </label>
                    <div className={styles.detailActions}>
                      <Button
                        disabled={
                          !input.trim() || Boolean(detail.cancel_requested)
                        }
                        loading={busy}
                        onClick={() => {
                          const text = input.trim();
                          void mutate(
                            JSON.stringify([
                              detail.task_id,
                              detail.current_attempt_id,
                              detail.current_run_id,
                              text,
                            ]),
                            (id) => workItemsApi.input(detail, text, id),
                            () => setInput(""),
                          );
                        }}
                      >
                        {t("chat.workItems.sendRequirements")}
                      </Button>
                      <Button
                        danger
                        disabled={Boolean(detail.cancel_requested)}
                        loading={busy}
                        onClick={() => {
                          void mutate(
                            `cancel:${detail.task_id}`,
                            (id) => workItemsApi.cancel(detail.task_id, id),
                            () => undefined,
                          );
                        }}
                      >
                        {t(
                          detail.cancel_requested
                            ? "chat.workItems.status.cancelling"
                            : "chat.workItems.cancel",
                        )}
                      </Button>
                    </div>
                  </>
                )}
              </>
            ) : (
              <p className={styles.hint}>{t("chat.workItems.chooseTask")}</p>
            )}
          </section>
        </div>
      </Drawer>
    </div>
  );
}
