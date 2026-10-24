import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Drawer,
  Collapse,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Spin,
  Switch,
  Tag,
  Typography,
} from "antd";
import {
  Archive,
  ArrowRight,
  CheckCircle2,
  Clock3,
  ListTree,
  Play,
  Plus,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { message } from "@/utils/antdMessage";
import {
  taskBoardApi,
  type BoardOperation,
  type BoardSnapshot,
  type BoardTask,
  type TaskDraft,
  type TaskStatus,
} from "../../api/modules/taskBoard";
import { teamsApi, type TeamRecord } from "../../api/modules/teams";
import { providerApi } from "../../api/modules/provider";
import { devicesApi, type Device } from "../../api/modules/devices";
import type { ResolvedModel } from "../../api/types";
import { buildModelSelectOptions } from "../../utils/modelOptions";
import { useAgent } from "../../context/AgentContext";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import { useUnsavedChangesWarning } from "../../hooks/useUnsavedChangesWarning";
import { formatServerIsoDateTime } from "../../utils/formatMessageTime";
import { apiErrorMessage } from "../../utils/apiError";
import PageShell from "../../layouts/PageShell";
import "./taskBoard.css";

const states: TaskStatus[] = ["planning", "todo", "running", "done", "failed"];
const colors = {
  planning: "#88909b",
  todo: "#5278d3",
  running: "#d29532",
  done: "#36a57a",
  failed: "#d65f73",
};
export function tagColor(name: string) {
  let hash = 0;
  for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return `hsl(${hash % 360} 42% 44%)`;
}

export default function TaskBoardPage() {
  const { t } = useTranslation();
  const tr = (key: string) => t(`octopus.${key}`);
  const navigate = useNavigate();
  const [search, setSearch] = useSearchParams();
  const { agents } = useAgent();
  const timezone = useServerTimezone();
  const [board, setBoard] = useState<BoardSnapshot | null>(null);
  const [teams, setTeams] = useState<TeamRecord[]>([]);
  const [query, setQuery] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [archived, setArchived] = useState(false);
  const [showChildren, setShowChildren] = useState(false);
  const [models, setModels] = useState<ResolvedModel[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [tagManager, setTagManager] = useState(false);
  const [tagName, setTagName] = useState("");
  const [tagRename, setTagRename] = useState("");
  const [tagPrefix, setTagPrefix] = useState("");
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [editor, setEditor] = useState<
    "create" | "edit" | "handover" | "review" | "schedule" | null
  >(null);
  const [aiNote, setAiNote] = useState("");
  const [editorRevision, setEditorRevision] = useState(0);
  const [form] = Form.useForm();
  const [modalApi, modalContext] = Modal.useModal();
  const [editorDirty, setEditorDirty] = useState(false);
  useUnsavedChangesWarning(Boolean(editor) && (editorDirty || busy));
  const project = search.get("project") || "";
  const memberFilter = search.get("agent") || "";
  const executors = agents.filter((agent) => agent.is_owner !== false);
  const formProject = Form.useWatch("project_id", form) as string | undefined;
  const scopeProject = editor === "create" ? formProject || "" : taskProject();
  function taskProject() {
    return (
      board?.tasks.find((item) => item.id === selected)?.project_id || project
    );
  }
  const executorOptions = executors
    .filter(
      (agent) =>
        !scopeProject ||
        agent.agent_id === scopeProject ||
        teams
          .find((team) => team.team_id === scopeProject)
          ?.member_ids.includes(agent.agent_id),
    )
    .map((agent) => ({ value: agent.agent_id, label: agent.name }));
  const reload = useCallback(async () => {
    try {
      const next = await taskBoardApi.get();
      setBoard(next);
      setError("");
    } catch (err) {
      setError(apiErrorMessage(err, t("octopus.loadFailed"), t));
    } finally {
      setLoading(false);
    }
  }, [t]);
  useEffect(() => {
    void reload();
    void devicesApi
      .list()
      .then((response) => setDevices(response.devices))
      .catch(() => setDevices([]));
    void providerApi
      .listResolvedModels()
      .then(setModels)
      .catch(() => setModels([]));
    void teamsApi
      .list()
      .then(setTeams)
      .catch((err) =>
        setError(apiErrorMessage(err, t("octopus.loadFailed"), t)),
      );
  }, [reload, t]);
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) void reload();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [reload]);
  const task = board?.tasks.find((item) => item.id === selected);
  const activeRun = task?.runs.at(-1)?.state === "running";
  const childTasks =
    board?.tasks.filter((item) => item.parent_id === selected) || [];
  const visible =
    board?.tasks.filter(
      (item) =>
        item.archived === archived &&
        (!project || item.project_id === project) &&
        (!memberFilter || item.agent_id === memberFilter) &&
        (archived ||
          showChildren ||
          !item.parent_id ||
          Boolean(query || tags.length || memberFilter)) &&
        tags.every((tag) => item.tags.includes(tag)) &&
        `${item.title} ${item.description} ${item.goal} ${item.progress} ${
          item.next_step
        } ${item.tags.join(" ")}`
          .toLowerCase()
          .includes(query.toLowerCase()),
    ) || [];
  const allTags = [
    ...new Set(
      board?.tasks
        .filter(
          (item) =>
            item.archived === archived &&
            (!project || item.project_id === project),
        )
        .flatMap((item) => item.tags),
    ),
  ].sort();
  async function act(
    action: BoardOperation,
    id: string,
    payload: Record<string, unknown> = {},
    revision = board?.revision,
  ) {
    if (!board || busy) return false;
    setBusy(true);
    try {
      setBoard(
        await taskBoardApi.act(revision ?? board.revision, action, id, payload),
      );
      setError("");
      setActionError("");
      return true;
    } catch (err) {
      const reason = apiErrorMessage(err, tr("actionFailed"), t);
      message.error(reason);
      await reload();
      setActionError(reason);
      return false;
    } finally {
      setBusy(false);
    }
  }
  const open = useCallback(
    (mode: NonNullable<typeof editor>, item?: BoardTask) => {
      setEditorRevision(board?.revision || 0);
      form.resetFields();
      setAiNote("");
      setEditorDirty(false);
      if (item) setSelected(item.id);
      form.setFieldsValue(
        mode === "create"
          ? {
              project_id: item?.project_id || project,
              parent_id: item?.id || "",
              tags: [],
              agent_id: item?.agent_id,
              acceptance: "automatic",
              auto_repair: false,
              continue_session: false,
              model: "",
              reviewer_model: "",
            }
          : mode === "schedule"
          ? item?.schedule || { cron: "0 9 * * *", timezone, enabled: true }
          : mode === "review"
          ? { scores: [65, 65, 65], evidence: "" }
          : item,
      );
      setEditor(mode);
    },
    [board?.revision, form, project, timezone],
  );
  useEffect(() => {
    if (board && search.get("new") === "1") {
      open("create");
      const next = new URLSearchParams(search);
      next.delete("new");
      setSearch(next, { replace: true });
    }
  }, [board, search, open, setSearch]);
  async function save() {
    const values = await form.validateFields().catch(() => null);
    if (!values) return;
    let payload = values as Record<string, unknown>;
    if (editor === "edit")
      payload = {
        title: values.title,
        description: values.description || "",
        prompt: values.prompt || "",
        tags: values.tags || [],
        goal: values.goal || values.description || values.title,
        progress: values.progress || "",
        next_step: values.next_step || "",
        model: values.model || "",
        device_id: values.device_id || "",
        reviewer_model: values.reviewer_model || "",
        acceptance: values.acceptance,
        auto_repair: Boolean(values.auto_repair),
        continue_session: Boolean(values.continue_session),
      };
    if (editor === "review")
      payload = {
        scores: [values.score0, values.score1, values.score2],
        evidence: values.evidence,
      };
    if (
      editor &&
      (await act(
        editor === "edit" ? "update" : editor,
        editor === "create" ? "" : selected || "",
        payload,
        editorRevision,
      ))
    )
      setEditor(null);
  }
  async function parse() {
    const agent = form.getFieldValue("agent_id") as string;
    if (!agent || !aiNote.trim()) {
      message.warning(tr("aiNeedsAgent"));
      return;
    }
    setBusy(true);
    try {
      const draft: TaskDraft = await taskBoardApi.parse(
        agent,
        aiNote,
        form.getFieldValue("model") || "",
      );
      setEditorDirty(true);
      form.setFieldsValue({
        title: draft.title,
        description: draft.description,
        prompt: draft.prompt,
        tags: draft.tags,
      });
    } catch (err) {
      setError(apiErrorMessage(err, tr("actionFailed"), t));
    } finally {
      setBusy(false);
    }
  }
  const field = (name: string, multiline = false, required = false) => (
    <Form.Item
      name={name}
      label={tr(name)}
      rules={required ? [{ required: true, whitespace: true }] : []}
    >
      {multiline ? <Input.TextArea rows={3} /> : <Input />}
    </Form.Item>
  );
  return (
    <PageShell
      title={tr("board")}
      subtitle={t("uiFeedback.boardHelp")}
      actions={
        <Space>
          <Button icon={<RefreshCw size={15} />} onClick={() => void reload()}>
            {tr("refresh")}
          </Button>
          <Button
            type="primary"
            icon={<Plus size={15} />}
            onClick={() => open("create")}
            disabled={!board}
          >
            {tr("newTask")}
          </Button>
        </Space>
      }
    >
      {modalContext}
      {error && (
        <Alert
          type="error"
          showIcon
          message={error}
          closable
          onClose={() => setError("")}
          style={{ marginBottom: 16 }}
        />
      )}
      {actionError && (
        <Alert
          type="error"
          showIcon
          message={actionError}
          closable
          onClose={() => setActionError("")}
          style={{ marginBottom: 16 }}
        />
      )}
      <div className="octopus-board-filters">
        <Select
          aria-label={tr("project")}
          value={project}
          onChange={(value) => {
            const next = new URLSearchParams(search);
            if (value) next.set("project", value);
            else next.delete("project");
            setSearch(next);
          }}
          options={[
            { value: "", label: tr("allProjects") },
            ...teams.map((team) => ({ value: team.team_id, label: team.name })),
          ]}
          style={{ minWidth: 190 }}
        />
        <Input.Search
          aria-label={tr("search")}
          placeholder={tr("search")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ maxWidth: 340 }}
        />
        <Button
          type={archived ? "primary" : "default"}
          icon={<Archive size={15} />}
          onClick={() => setArchived(!archived)}
        >
          {tr("archive")} (
          {board?.tasks.filter((item) => item.archived).length || 0})
        </Button>
        {project && (
          <Button onClick={() => navigate(`/chat/${project}`)}>
            {tr("groupChat")} <ArrowRight size={14} />
          </Button>
        )}
        <Button
          icon={<ListTree size={15} />}
          type={showChildren ? "primary" : "default"}
          onClick={() => setShowChildren(!showChildren)}
        >
          {tr("showChildren")}
        </Button>
        {memberFilter && (
          <Tag
            closable
            onClose={() => {
              search.delete("agent");
              setSearch(search);
            }}
          >
            {agents.find((item) => item.agent_id === memberFilter)?.name ||
              memberFilter}
          </Tag>
        )}
      </div>
      <div className="octopus-board-tags" aria-label={tr("tags")}>
        <Button type="text" size="small" onClick={() => setTagManager(true)}>
          {tr("manageTags")}
        </Button>
        {allTags.map((tag) => (
          <button
            key={tag}
            className={tags.includes(tag) ? "selected" : ""}
            style={{ color: tagColor(tag), borderColor: tagColor(tag) }}
            onClick={() =>
              setTags(
                tags.includes(tag)
                  ? tags.filter((item) => item !== tag)
                  : [...tags, tag],
              )
            }
          >
            {tag}
          </button>
        ))}
        {tags.length > 0 && (
          <Button type="link" onClick={() => setTags([])}>
            {tr("clearFilters")}
          </Button>
        )}
      </div>
      {loading && (
        <div style={{ padding: 24, textAlign: "center" }} role="status">
          <Spin /> {t("uiFeedback.taskLoad")}
        </div>
      )}
      {!loading && board && visible.length === 0 && (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            query.trim() || tags.length || memberFilter
              ? t("uiFeedback.noMatchingTasks")
              : tr("noTasks")
          }
        >
          {(query.trim() || tags.length > 0 || memberFilter) && (
            <Button
              onClick={() => {
                setQuery("");
                setTags([]);
                const next = new URLSearchParams(search);
                next.delete("agent");
                setSearch(next);
              }}
            >
              {tr("clearFilters")}
            </Button>
          )}
        </Empty>
      )}
      {board && (
        <div className="octopus-board-columns" aria-busy={busy || loading}>
          {states.map((status) => (
            <section
              key={status}
              className="octopus-board-column"
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                const id = event.dataTransfer.getData(
                  "application/octopus-task",
                );
                if (id && !archived && status !== "running")
                  void act("move", id, { status });
              }}
              aria-label={tr(status)}
            >
              <header>
                <span style={{ background: colors[status] }} />{" "}
                <strong>{tr(status)}</strong>
                <small>
                  {visible.filter((item) => item.status === status).length}
                </small>
              </header>
              {visible
                .filter((item) => item.status === status)
                .map((item) => (
                  <article
                    key={item.id}
                    className={`octopus-task ${item.status}`}
                    draggable={
                      !archived &&
                      !busy &&
                      item.runs.at(-1)?.state !== "running"
                    }
                    onDragStart={(event) =>
                      event.dataTransfer.setData(
                        "application/octopus-task",
                        item.id,
                      )
                    }
                  >
                    <button
                      className="octopus-task-open"
                      onClick={() => setSelected(item.id)}
                    >
                      <strong>{item.title}</strong>
                      <div className="octopus-task-tags">
                        {item.tags.map((tag) => (
                          <Tag key={tag} color={tagColor(tag)}>
                            {tag}
                          </Tag>
                        ))}
                      </div>
                      <p>{item.description}</p>
                    </button>
                    <footer>
                      <span>
                        {agents.find(
                          (agent) => agent.agent_id === item.agent_id,
                        )?.name || tr("unassigned")}
                      </span>
                      <span>
                        {item.runs.length} {tr("runs")}
                      </span>
                    </footer>
                    <small>
                      {formatServerIsoDateTime(item.updated_at, timezone)}
                    </small>
                    {item.runs.at(-1)?.state === "running" && (
                      <small style={{ color: colors.running }}>
                        {tr(
                          item.runs.at(-1)?.phase === "reviewing"
                            ? "reviewing"
                            : "executing",
                        )}
                      </small>
                    )}
                    {item.runs.at(-1) &&
                      item.runs.at(-1)?.state !== "running" && (
                        <div
                          className="octopus-run-state"
                          data-state={item.runs.at(-1)?.state}
                        >
                          {t(
                            `uiFeedback.${
                              item.runs.at(-1)?.state === "failed"
                                ? "taskFailed"
                                : item.runs.at(-1)?.state === "interrupted"
                                ? "taskInterrupted"
                                : "taskSucceeded"
                            }`,
                          )}
                        </div>
                      )}
                    {item.schedule && (
                      <small>
                        <Clock3 size={12} /> {item.schedule.cron} ·{" "}
                        {item.schedule.timezone}
                      </small>
                    )}
                    {board?.tasks.some(
                      (child) => child.parent_id === item.id,
                    ) && (
                      <small>
                        <ListTree size={12} />{" "}
                        {
                          board.tasks.filter(
                            (child) =>
                              child.parent_id === item.id &&
                              child.status === "done",
                          ).length
                        }
                        /
                        {
                          board.tasks.filter(
                            (child) => child.parent_id === item.id,
                          ).length
                        }{" "}
                        {tr("children")}
                      </small>
                    )}
                    {item.runs.at(-1)?.state === "succeeded" &&
                      !item.review && (
                        <small style={{ color: colors.running }}>
                          {tr("awaitingReview")}
                        </small>
                      )}
                    {!item.pin && <small>{tr("needsConfirmation")}</small>}
                  </article>
                ))}
              {visible.filter((item) => item.status === status).length ===
                0 && (
                <div className="octopus-column-empty">{tr("noTasks")}</div>
              )}
            </section>
          ))}
        </div>
      )}
      <Drawer
        width="min(620px, 100vw)"
        open={Boolean(task)}
        onClose={() => setSelected(null)}
        title={task?.title}
        destroyOnClose
      >
        {task && (
          <>
            <Space wrap>
              <Tag color={colors[task.status]}>{tr(task.status)}</Tag>
              <Typography.Text type="secondary">
                {formatServerIsoDateTime(task.updated_at, timezone)}
              </Typography.Text>
              {task.archived && <Tag>{tr("archive")}</Tag>}
            </Space>
            <Typography.Paragraph
              style={{ marginTop: 20, whiteSpace: "pre-wrap" }}
            >
              {task.description}
            </Typography.Paragraph>
            <Typography.Text strong>{tr("prompt")}</Typography.Text>
            <pre className="octopus-task-prompt">
              {task.prompt || task.title}
            </pre>
            <Collapse
              size="small"
              style={{ marginBottom: 18 }}
              items={[
                {
                  key: "snapshot",
                  label: tr("frozenSnapshot"),
                  children: (
                    <>
                      <p>
                        <strong>{tr("goal")}</strong>
                        <br />
                        {task.goal}
                      </p>
                      <p>
                        <strong>{tr("progress")}</strong>
                        <br />
                        {task.progress || "—"}
                      </p>
                      <p>
                        <strong>{tr("next_step")}</strong>
                        <br />
                        {task.next_step || "—"}
                      </p>
                      <p>
                        {task.acceptance === "automatic"
                          ? tr("automaticReview")
                          : tr("humanReview")}{" "}
                        · {task.model || tr("defaultModel")}
                      </p>
                    </>
                  ),
                },
              ]}
            />
            <Space wrap style={{ marginBottom: 24 }}>
              {task.archived ? (
                <Button onClick={() => void act("restore", task.id)}>
                  {tr("restore")}
                </Button>
              ) : (
                <>
                  <Button
                    disabled={activeRun}
                    onClick={() => open("edit", task)}
                  >
                    {tr("edit")}
                  </Button>
                  <Button
                    disabled={activeRun}
                    onClick={() => open("handover", task)}
                  >
                    {tr("handover")}
                  </Button>
                  <Button
                    disabled={activeRun || !task.agent_id}
                    icon={<CheckCircle2 size={15} />}
                    onClick={() =>
                      Modal.confirm({
                        title: tr("confirmProfile"),
                        content: tr("confirmProfileHelp"),
                        onOk: async () => {
                          await act("confirm", task.id, {
                            cascade: childTasks.length > 0,
                          });
                        },
                      })
                    }
                  >
                    {tr("confirmProfile")}
                  </Button>
                  <Button
                    type="primary"
                    icon={<Play size={15} />}
                    disabled={activeRun || !task.pin}
                    loading={busy}
                    onClick={() =>
                      void act("run", task.id, {
                        request_id: crypto.randomUUID(),
                        cascade: true,
                      })
                    }
                  >
                    {tr(childTasks.length ? "runTree" : "run")}
                  </Button>
                  {activeRun && (
                    <Button
                      danger
                      onClick={() =>
                        void act("cancel", task.id, { cascade: true })
                      }
                    >
                      {tr("cancelRun")}
                    </Button>
                  )}
                  <Button
                    disabled={activeRun}
                    onClick={() => open("schedule", task)}
                  >
                    {tr("schedule")}
                  </Button>
                  <Button
                    disabled={activeRun}
                    onClick={() => void act("archive", task.id)}
                  >
                    {tr("archive")}
                  </Button>
                </>
              )}
            </Space>
            {!task.archived && (
              <>
                <Select
                  aria-label={tr("running")}
                  style={{ width: "100%" }}
                  disabled={activeRun}
                  value={task.status}
                  onChange={(status) => void act("move", task.id, { status })}
                  options={states.map((status) => ({
                    value: status,
                    label: tr(status),
                    disabled: status === "running",
                  }))}
                />
                <Typography.Title level={5}>{tr("parent")}</Typography.Title>
                <Select
                  style={{ width: "100%" }}
                  disabled={activeRun}
                  value={task.parent_id}
                  onChange={(parent_id) =>
                    void act("parent", task.id, { parent_id })
                  }
                  options={[
                    { value: "", label: tr("noParent") },
                    ...(
                      board?.tasks.filter(
                        (item) =>
                          item.id !== task.id &&
                          !item.archived &&
                          item.project_id === task.project_id,
                      ) || []
                    ).map((item) => ({ value: item.id, label: item.title })),
                  ]}
                />
              </>
            )}
            <Typography.Title level={5}>{tr("children")}</Typography.Title>
            {!task.archived && (
              <Button
                icon={<Plus size={14} />}
                disabled={activeRun}
                onClick={() => open("create", task)}
                style={{ marginBottom: 12 }}
              >
                {tr("newChild")}
              </Button>
            )}
            {childTasks.length ? (
              childTasks.map((child) => (
                <Button
                  key={child.id}
                  block
                  type="text"
                  style={{ textAlign: "left" }}
                  onClick={() => setSelected(child.id)}
                >
                  {tr(child.status)} · {child.title}
                </Button>
              ))
            ) : (
              <Typography.Text type="secondary">
                {tr("noChildren")}
              </Typography.Text>
            )}
            {task.schedule && (
              <Alert
                style={{ marginTop: 20 }}
                message={`${task.schedule.cron} · ${task.schedule.timezone}`}
                description={`${
                  task.schedule.enabled ? tr("enabled") : tr("disabled")
                } · ${tr("nextRun")}: ${
                  task.schedule.next_run
                    ? formatServerIsoDateTime(
                        task.schedule.next_run,
                        task.schedule.timezone,
                      )
                    : "—"
                }`}
              />
            )}
            <Typography.Title level={5}>{tr("history")}</Typography.Title>
            {!task.runs.length && (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={tr("noRuns")}
              />
            )}
            {[...task.runs].reverse().map((run) => (
              <div key={run.id} className="octopus-run">
                <Space>
                  <Tag>{tr(run.state)}</Tag>
                  <span>
                    {formatServerIsoDateTime(run.started_at, timezone)}
                  </span>
                </Space>
                {run.thread_id && (
                  <Button
                    type="link"
                    onClick={() =>
                      navigate(`/chat/${run.agent_id}/${run.thread_id}`)
                    }
                  >
                    {tr("viewSession")}
                  </Button>
                )}
                <pre>{run.output || run.error || tr("executing")}</pre>
                {run.acceptance_error && (
                  <Alert
                    type="warning"
                    message={tr("reviewError")}
                    description={run.acceptance_error}
                    action={
                      run.id === task.runs.at(-1)?.id &&
                      !task.archived &&
                      !activeRun ? (
                        <Button onClick={() => void act("verify", task.id)}>
                          {tr("retryReview")}
                        </Button>
                      ) : undefined
                    }
                  />
                )}
                {run.phase === "reviewing" && (
                  <Tag color="gold">{tr("reviewing")}</Tag>
                )}
                {run.review && (
                  <Alert
                    type={run.review.passed ? "success" : "error"}
                    message={`${tr(
                      run.review.model ? "automaticReview" : "humanReview",
                    )} · ${run.review.scores.join(" / ")}`}
                    description={
                      run.review.model ? undefined : run.review.evidence
                    }
                  />
                )}
                {run.review?.model && (
                  <Collapse
                    size="small"
                    items={[
                      {
                        key: "details",
                        label: `${run.review.model} · ${tr("twoRounds")}`,
                        children: (
                          <>
                            <p>
                              {tr("baseline")}:{" "}
                              {run.review.baseline_scores.join(" / ")} ·{" "}
                              {tr("evidenceSize")}: {run.review.evidence_chars}{" "}
                              / {tr("truncated")}: {run.review.truncated_chars}
                            </p>
                            {run.review.rounds.map((row, index) => (
                              <p key={index}>
                                {
                                  [
                                    tr("adherence"),
                                    tr("outputMatch"),
                                    tr("errorDetection"),
                                  ][row.criterion]
                                }{" "}
                                · {row.round}: {row.score} / {row.baseline}
                                <br />
                                {row.evidence}
                              </p>
                            ))}
                            <p>
                              {tr("repairAttempts")}: {run.attempts.length}
                            </p>
                          </>
                        ),
                      },
                    ]}
                  />
                )}
                {run.id === task.runs.at(-1)?.id &&
                  run.state === "succeeded" &&
                  !activeRun &&
                  !task.archived && (
                    <Button onClick={() => open("review", task)}>
                      {tr("independentReview")}
                    </Button>
                  )}
              </div>
            ))}
            <Typography.Title level={5}>{tr("handover")}</Typography.Title>
            {[...task.handovers].reverse().map((item, index) => (
              <div key={index} className="octopus-run">
                <strong>
                  {item.from_agent} → {item.to_agent}
                </strong>
                <p>
                  {tr("goal")}: {item.goal}
                </p>
                <p>
                  {tr("progress")}: {item.progress}
                </p>
                <p>
                  {tr("next_step")}: {item.next_step}
                </p>
              </div>
            ))}
          </>
        )}
      </Drawer>
      <Modal
        open={Boolean(editor)}
        width={660}
        title={tr(editor || "newTask")}
        onCancel={() => {
          if (busy) return;
          if (!editorDirty) {
            setEditor(null);
            return;
          }
          modalApi.confirm({
            title: t("uiFeedback.discardTitle"),
            content: t("uiFeedback.discardBody"),
            okText: t("uiFeedback.discard"),
            cancelText: t("uiFeedback.keepEditing"),
            onOk: () => setEditor(null),
          });
        }}
        onOk={() => void save()}
        confirmLoading={busy}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          preserve={false}
          onValuesChange={() => setEditorDirty(true)}
        >
          {editor === "create" && (
            <Form.Item name="parent_id" hidden>
              <Input />
            </Form.Item>
          )}
          {(editor === "create" || editor === "edit") && (
            <>
              {editor === "create" && (
                <>
                  <Form.Item name="project_id" label={tr("project")}>
                    <Select
                      options={[
                        { value: "", label: tr("noProject") },
                        ...teams.map((team) => ({
                          value: team.team_id,
                          label: team.name,
                        })),
                      ]}
                    />
                  </Form.Item>
                  <Form.Item name="agent_id" label={tr("executor")}>
                    <Select
                      showSearch
                      optionFilterProp="label"
                      options={executorOptions}
                    />
                  </Form.Item>
                  <div className="octopus-ai-draft">
                    <strong>
                      <Sparkles size={14} /> {tr("aiDraft")}
                    </strong>
                    <Input.TextArea
                      value={aiNote}
                      onChange={(event) => {
                        setAiNote(event.target.value);
                        setEditorDirty(true);
                      }}
                      rows={3}
                      placeholder={tr("aiPlaceholder")}
                    />
                    <Button loading={busy} onClick={() => void parse()}>
                      {tr("parseFill")}
                    </Button>
                  </div>
                </>
              )}
              {field("title", false, true)}
              {field("description", true)}
              {field("prompt", true)}
              <Form.Item name="device_id" label={t("devices.targetDevice")}>
                <Select
                  allowClear
                  placeholder={t("devices.noTarget")}
                  options={devices
                    .filter((d) => d.revoked_at === null)
                    .map((d) => ({
                      value: d.device_id,
                      label: `${d.name} · ${t(
                        d.online ? "devices.online" : "devices.offline",
                      )}`,
                    }))}
                />
              </Form.Item>
              <Form.Item name="tags" label={tr("tags")}>
                <Select mode="tags" tokenSeparators={[","]} />
              </Form.Item>
              <Collapse
                size="small"
                items={[
                  {
                    key: "execution",
                    forceRender: true,
                    label: tr("executionSettings"),
                    children: (
                      <>
                        <Form.Item name="model" label={tr("model")}>
                          <Select
                            options={buildModelSelectOptions(
                              models,
                              tr("defaultModel"),
                            )}
                          />
                        </Form.Item>
                        <Form.Item
                          name="acceptance"
                          label={tr("independentReview")}
                        >
                          <Select
                            options={[
                              {
                                value: "automatic",
                                label: tr("automaticReview"),
                              },
                              { value: "manual", label: tr("humanReview") },
                            ]}
                          />
                        </Form.Item>
                        <Form.Item
                          name="reviewer_model"
                          label={tr("reviewerModel")}
                        >
                          <Select
                            options={buildModelSelectOptions(
                              models,
                              tr("defaultModel"),
                            )}
                          />
                        </Form.Item>
                        <Form.Item
                          name="auto_repair"
                          label={tr("autoRepair")}
                          valuePropName="checked"
                        >
                          <Switch />
                        </Form.Item>
                        <Form.Item
                          name="continue_session"
                          label={tr("continueSession")}
                          valuePropName="checked"
                        >
                          <Switch />
                        </Form.Item>
                      </>
                    ),
                  },
                  ...(editor === "edit"
                    ? [
                        {
                          key: "snapshot",
                          forceRender: true,
                          label: tr("frozenSnapshot"),
                          children: (
                            <>
                              {field("goal", true)}
                              {field("progress", true)}
                              {field("next_step", true)}
                            </>
                          ),
                        },
                      ]
                    : []),
                ]}
              />
            </>
          )}
          {editor === "handover" && (
            <>
              <Form.Item
                name="agent_id"
                label={tr("executor")}
                rules={[{ required: true }]}
              >
                <Select options={executorOptions} />
              </Form.Item>
              {field("goal", true, true)}
              {field("progress", true)}
              {field("next_step", true, true)}
              <Alert message={tr("handoverHelp")} />
            </>
          )}
          {editor === "schedule" && (
            <>
              {field("cron", false, true)}
              {field("timezone", false, true)}
              <Form.Item
                name="enabled"
                label={tr("enabled")}
                valuePropName="checked"
              >
                <Switch />
              </Form.Item>
              <Alert message={tr("scheduleHelp")} />
            </>
          )}
          {editor === "review" && (
            <>
              <Alert style={{ marginBottom: 18 }} message={tr("reviewHelp")} />
              {["adherence", "outputMatch", "errorDetection"].map(
                (key, index) => (
                  <Form.Item
                    key={key}
                    name={`score${index}`}
                    label={tr(key)}
                    rules={[{ required: true }]}
                  >
                    <InputNumber min={0} max={100} />
                  </Form.Item>
                ),
              )}
              {field("evidence", true, true)}
            </>
          )}
        </Form>
      </Modal>
      <Modal
        open={tagManager}
        title={tr("manageTags")}
        onCancel={() => setTagManager(false)}
        footer={null}
      >
        <Select
          style={{ width: "100%", marginBottom: 16 }}
          placeholder={tr("tags")}
          value={tagName || undefined}
          options={[...new Set(board?.tasks.flatMap((item) => item.tags))]
            .sort()
            .map((value) => ({ value, label: value }))}
          onChange={(value) => {
            setTagName(value);
            setTagRename(value);
            setTagPrefix(board?.tag_prefixes[value] || "");
          }}
        />
        <label>
          {tr("renameTag")}
          <Input
            value={tagRename}
            onChange={(event) => setTagRename(event.target.value)}
            style={{ marginBottom: 16 }}
          />
        </label>
        <label>
          {tr("tagPrefix")}
          <Input.TextArea
            rows={3}
            value={tagPrefix}
            onChange={(event) => setTagPrefix(event.target.value)}
            style={{ marginBottom: 16 }}
          />
        </label>
        <Space>
          <Button
            type="primary"
            disabled={!tagName || !tagRename.trim()}
            onClick={() =>
              void act("tags", "", {
                name: tagName,
                rename: tagRename,
                prefix: tagPrefix,
              }).then((ok) => {
                if (ok) {
                  setTags([]);
                  setTagManager(false);
                }
              })
            }
          >
            {tr("save")}
          </Button>
          <Button
            danger
            disabled={!tagName}
            onClick={() =>
              void act("tags", "", { name: tagName, rename: "" }).then((ok) => {
                if (ok) {
                  setTags(tags.filter((tag) => tag !== tagName));
                  setTagManager(false);
                }
              })
            }
          >
            {tr("removeTag")}
          </Button>
        </Space>
      </Modal>
    </PageShell>
  );
}
