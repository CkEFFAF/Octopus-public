import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Pagination,
  Popover,
  Tooltip,
  Select,
  Space,
  Spin,
  Tag,
} from "antd";
import {
  Archive,
  Download,
  GitBranch,
  Play,
  Plus,
  Redo2,
  Save,
  Settings2,
  Trash2,
  Undo2,
  Upload,
  ChevronDown,
  ChevronUp,
  FolderTree,
  X,
  History,
} from "lucide-react";
import { message } from "../../utils/antdMessage";
import { apiErrorMessage } from "../../utils/apiError";
import { useAgent } from "../../context/AgentContext";
import { useUnsavedChangesWarning } from "../../hooks/useUnsavedChangesWarning";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import { formatServerDateTime } from "../../utils/formatMessageTime";
import { NodeIcon } from "./nodePresentation";
import {
  workflowGraphsApi as api,
  type Activation,
  type GraphDefinition,
  type GraphRun,
  type GraphSummary,
  type GraphView,
  type Issue,
} from "../../api/modules/workflowGraphs";
import { GraphCanvas } from "./GraphCanvas";
import { Inspector, JsonField } from "./Inspector";
import { example, kinds, makeNode } from "./definitions";
import "./workflowGraphs.css";

export default function WorkflowGraphs() {
  const { t } = useTranslation();
  const tr = useCallback((key: string) => t(`workflowGraph.${key}`), [t]);
  const { agents } = useAgent();
  const timezone = useServerTimezone();
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [runsExpanded, setRunsExpanded] = useState(false);
  const [runDefinition, setRunDefinition] = useState<GraphDefinition | null>(
    null,
  );
  const [showRun, setShowRun] = useState(false);
  const [catalog, setCatalog] = useState<GraphSummary[]>([]),
    [catalogTotal, setCatalogTotal] = useState(0),
    [catalogOffset, setCatalogOffset] = useState(0);
  const [view, setView] = useState<GraphView | null>(null),
    [draft, setDraft] = useState<GraphDefinition | null>(null);
  const [selected, setSelected] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [issues, setIssues] = useState<Issue[]>([]);
  const [past, setPast] = useState<GraphDefinition[]>([]),
    [future, setFuture] = useState<GraphDefinition[]>([]);
  const [createOpen, setCreateOpen] = useState(false),
    [newId, setNewId] = useState(""),
    [template, setTemplate] = useState<
      "blank" | "daily" | "iteration" | "event"
    >("blank");
  const [runs, setRuns] = useState<GraphRun[]>([]),
    [run, setRun] = useState<GraphRun | null>(null),
    [timeline, setTimeline] = useState<Activation[]>([]),
    [timelineTotal, setTimelineTotal] = useState(0),
    [offset, setOffset] = useState(0);
  const [detail, setDetail] = useState<Activation | null>(null),
    [runOpen, setRunOpen] = useState(false),
    [variables, setVariables] = useState<Record<string, unknown>>({}),
    [requestId, setRequestId] = useState("");
  const [budgetOpen, setBudgetOpen] = useState(false),
    [steps, setSteps] = useState(200),
    [seconds, setSeconds] = useState(86400);
  const [capability, setCapability] = useState<{
    callback_url: string;
    token: string;
  } | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const loadSequence = useRef(0);
  const [cancellationReceipts, setCancellationReceipts] = useState<
    unknown[] | null
  >(null);
  const dirty =
    !!draft && JSON.stringify(draft) !== JSON.stringify(view?.definition);
  useUnsavedChangesWarning(dirty);
  const reloadList = useCallback(async () => {
    const page = await api.list(catalogOffset);
    setCatalog(page.items);
    setCatalogTotal(page.total);
  }, [catalogOffset]);
  useEffect(() => {
    void reloadList().catch((e) =>
      setError(apiErrorMessage(e, tr("requestFailed"), t)),
    );
  }, [reloadList, t, tr]);
  const attempt = async <T,>(operation: () => Promise<T>) => {
    setBusy(true);
    setError("");
    try {
      return await operation();
    } catch (e) {
      setError(apiErrorMessage(e, tr("requestFailed"), t));
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  const changed = (next: GraphDefinition) => {
    if (!draft || JSON.stringify(next) === JSON.stringify(draft)) return;
    setPast((p) => [...p.slice(-49), draft]);
    setFuture([]);
    setDraft(next);
    setIssues([]);
  };
  const undo = () => {
    if (!draft || !past.length) return;
    setFuture((f) => [draft, ...f]);
    setDraft(past[past.length - 1]);
    setPast((p) => p.slice(0, -1));
  };
  const redo = () => {
    if (!draft || !future.length) return;
    setPast((p) => [...p, draft]);
    setDraft(future[0]);
    setFuture((f) => f.slice(1));
  };
  const install = (value: GraphView) => {
    setView(value);
    setDraft(value.definition);
    setIssues(value.issues);
    setSelected("");
    setPast([]);
    setFuture([]);
  };
  const confirmDiscard = (action: () => void) => {
    if (!dirty) action();
    else
      Modal.confirm({
        title: tr("discard"),
        content: tr("discardHelp"),
        onOk: action,
      });
  };
  const load = (identity: string) =>
    confirmDiscard(() => {
      const sequence = ++loadSequence.current;
      void attempt(async () => {
        const value = await api.get(identity);
        if (sequence !== loadSequence.current) return;
        install(value);
        setLibraryOpen(false);
        setSettingsOpen(false);
        setRun(null);
        setTimeline([]);
        const page = await api.runs(identity);
        if (sequence === loadSequence.current) setRuns(page.items);
      });
    });
  const save = async () => {
    if (!draft || !view) return;
    const value = await api.save(view.graph_id, view.revision, draft);
    install(value);
    await reloadList();
    return value;
  };
  const readonly = showRun && !!run && !!runDefinition;
  const editorGraph = readonly ? runDefinition : draft;
  const selectedNode = editorGraph?.nodes.find((n) => n.id === selected),
    selectedEdge = editorGraph?.edges.find((e) => e.id === selected);
  const remove = () => {
    if (!draft || !selected || readonly) return;
    changed({
      ...draft,
      nodes: draft.nodes.filter((n) => n.id !== selected),
      edges: draft.edges.filter(
        (e) =>
          e.id !== selected && e.source !== selected && e.target !== selected,
      ),
    });
    setSelected("");
  };
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (
        (e.target as HTMLElement).closest(
          "input,textarea,[contenteditable='true'],[role='combobox']",
        )
      )
        return;
      if (readonly) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
      }
      if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        remove();
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });
  const runId = run?.id;
  const runVersion = run?.version,
    runGraph = run?.graph_id;
  useEffect(() => {
    let stopped = false;
    setRunDefinition(null);
    if (!runGraph || !runVersion) {
      setShowRun(false);
      return;
    }
    void api
      .version(runGraph, runVersion)
      .then((value) => {
        if (!stopped) {
          setRunDefinition(value);
          setShowRun(true);
        }
      })
      .catch((e) => setError(apiErrorMessage(e, tr("requestFailed"), t)));
    return () => {
      stopped = true;
    };
  }, [runGraph, runVersion, runId, t, tr]);
  useEffect(() => {
    if (!runId) return;
    let stopped = false;
    const poll = async () => {
      try {
        const [value, page] = await Promise.all([
          api.run(runId),
          api.timeline(runId, offset),
        ]);
        if (!stopped) {
          setRun(value);
          setTimeline(page.items);
          setTimelineTotal(page.total);
        }
      } catch (e) {
        if (!stopped) setError(apiErrorMessage(e, tr("requestFailed"), t));
      }
    };
    void poll();
    const timer = window.setInterval(() => {
      if (!document.hidden) void poll();
    }, 3000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [runId, offset, t, tr]);
  const create = () =>
    confirmDiscard(() => {
      setNewId(`flow_${crypto.randomUUID().slice(0, 8)}`);
      setCreateOpen(true);
    });
  const exportGraph = () => {
    if (!draft) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(draft, null, 2)], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `${view?.graph_id || "workflow"}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };
  const runControl = (action: string) =>
    run && void attempt(async () => setRun(await api.control(run.id, action)));
  return (
    <section className="wg-shell" aria-label={tr("title")}>
      <header className="wg-header">
        <div className="wg-header-identity">
          <Button
            type="text"
            className="wg-workflow-picker"
            aria-label={tr("library")}
            onClick={() => setLibraryOpen(true)}
          >
            <FolderTree size={19} />
            <h1>{draft?.name || tr("title")}</h1>
            <ChevronDown size={15} />
          </Button>
          {view && (
            <>
              <span className="wg-header-divider" />
              <Tag>
                {readonly
                  ? `${tr("runVersion")} v${run?.version}`
                  : `${tr("draft")} v${view.revision}`}
              </Tag>
              {view.published_revision && (
                <span className="wg-published-state">
                  <i />
                  {tr("published")} v{view.published_revision}
                </span>
              )}
              {dirty && <span className="wg-dirty">{tr("unsaved")}</span>}
            </>
          )}
        </div>
        <Button
          icon={<Settings2 size={17} />}
          onClick={() => setSettingsOpen(true)}
          disabled={!draft}
        >
          {tr("settings")}
        </Button>
      </header>
      <div className="wg-page">
        <main className="wg-workbench">
          {error && (
            <Alert
              closable
              type="error"
              message={error}
              onClose={() => setError("")}
            />
          )}
          {draft && view ? (
            <>
              <div className="wg-editor">
                <div className="wg-add-tool">
                  <Popover
                    open={paletteOpen}
                    onOpenChange={setPaletteOpen}
                    trigger="click"
                    placement="bottomLeft"
                    content={
                      <div className="wg-node-menu">
                        <h3>{tr("addNode")}</h3>
                        <div>
                          {kinds.map((kind) => (
                            <button
                              key={kind}
                              className={`wg-node-option kind-${kind}`}
                              disabled={readonly || draft.nodes.length >= 64}
                              onClick={() => {
                                const node = makeNode(
                                  kind,
                                  `${tr(`kind.${kind}`)} ${
                                    draft.nodes.filter(
                                      (item) => item.kind === kind,
                                    ).length + 1
                                  }`,
                                  draft.nodes.length,
                                );
                                while (
                                  draft.nodes.some(
                                    (item) =>
                                      Math.abs(
                                        item.position.x - node.position.x,
                                      ) < 290 &&
                                      Math.abs(
                                        item.position.y - node.position.y,
                                      ) < 200,
                                  )
                                )
                                  node.position.y += 220;
                                changed({
                                  ...draft,
                                  nodes: [...draft.nodes, node],
                                });
                                setSelected(node.id);
                                setPaletteOpen(false);
                              }}
                            >
                              <span className="wg-node-option-icon">
                                <NodeIcon kind={kind} />
                              </span>
                              <span>
                                <strong>{tr(`kind.${kind}`)}</strong>
                                <small>{tr(`nodeHint.${kind}`)}</small>
                              </span>
                            </button>
                          ))}
                        </div>
                      </div>
                    }
                  >
                    <Button
                      size="large"
                      icon={<Plus size={18} />}
                      disabled={readonly}
                    >
                      {tr("addNode")}
                    </Button>
                  </Popover>
                </div>
                <GraphCanvas
                  key={`${view.graph_id}:${readonly ? run?.id : "draft"}`}
                  graph={editorGraph || draft}
                  selected={selected}
                  onSelect={setSelected}
                  onChange={changed}
                  activations={readonly ? run?.node_states ?? timeline : []}
                  readOnly={readonly}
                  tr={tr}
                />
                {(selectedNode || selectedEdge) && (
                  <aside className="wg-node-panel">
                    <div className="wg-panel-heading">
                      <strong>{tr("nodeSettings")}</strong>
                      <Space>
                        <Tooltip title={tr("delete")}>
                          <Button
                            type="text"
                            danger
                            aria-label={tr("delete")}
                            icon={<Trash2 size={16} />}
                            disabled={readonly}
                            onClick={remove}
                          />
                        </Tooltip>
                        <Button
                          type="text"
                          aria-label={tr("closeInspector")}
                          icon={<X size={17} />}
                          onClick={() => setSelected("")}
                        />
                      </Space>
                    </div>{" "}
                    {readonly ? (
                      <aside className="wg-inspector">
                        <h3>
                          {tr("runVersion")} v{run?.version}
                        </h3>
                        <p>{tr("readonlyHelp")}</p>
                        <pre className="wg-detail-json">
                          {JSON.stringify(
                            selectedNode || selectedEdge || editorGraph,
                            null,
                            2,
                          )}
                        </pre>
                      </aside>
                    ) : selectedEdge ? (
                      <aside className="wg-inspector">
                        <h3>{tr("connection")}</h3>
                        <Form layout="vertical">
                          <Form.Item label={tr("label")}>
                            <Input
                              value={selectedEdge.label}
                              onChange={(e) =>
                                changed({
                                  ...draft,
                                  edges: draft.edges.map((edge) =>
                                    edge.id === selected
                                      ? { ...edge, label: e.target.value }
                                      : edge,
                                  ),
                                })
                              }
                            />
                          </Form.Item>
                          <p>
                            {selectedEdge.source} → {selectedEdge.target}
                          </p>
                          <small>{selectedEdge.id}</small>
                          <Form.Item label={tr("portLabel")}>
                            <Select
                              value={selectedEdge.port}
                              options={["next", "true", "false", "error"].map(
                                (value) => ({
                                  value,
                                  label: tr(`port.${value}`),
                                }),
                              )}
                              onChange={(port) =>
                                changed({
                                  ...draft,
                                  edges: draft.edges.map((edge) =>
                                    edge.id === selected
                                      ? { ...edge, port }
                                      : edge,
                                  ),
                                })
                              }
                            />
                          </Form.Item>
                        </Form>
                      </aside>
                    ) : (
                      <Inspector
                        graph={draft}
                        node={selectedNode}
                        onChange={changed}
                        agents={agents}
                        tr={tr}
                      />
                    )}
                  </aside>
                )}
              </div>

              {!!issues.length && (
                <div className="wg-issues" role="alert">
                  {issues.map((issue, i) => (
                    <button
                      key={i}
                      onClick={() =>
                        setSelected(issue.node_id || issue.edge_id || "")
                      }
                    >
                      {issue.node_id || issue.edge_id} {issue.message}
                    </button>
                  ))}
                </div>
              )}
              <section className={`wg-runs ${runsExpanded ? "expanded" : ""}`}>
                <div className="wg-footer">
                  <Button
                    type="text"
                    size="small"
                    aria-expanded={runsExpanded}
                    icon={<History size={15} />}
                    onClick={() => setRunsExpanded((value) => !value)}
                  >
                    {tr("runs")}
                    {runsExpanded ? (
                      <ChevronDown size={14} />
                    ) : (
                      <ChevronUp size={14} />
                    )}
                  </Button>
                  <div>
                    {run && <Tag>{tr(`status.${run.status}`)}</Tag>}
                    <span>
                      {(editorGraph || draft).nodes.length} {tr("nodes")} /{" "}
                      {(editorGraph || draft).edges.length} {tr("connections")}
                    </span>
                    {dirty && <span className="wg-dirty">{tr("unsaved")}</span>}
                  </div>
                </div>
                {runsExpanded && (
                  <>
                    {" "}
                    <div className="wg-run-toolbar">
                      <Select
                        placeholder={tr("chooseRun")}
                        style={{ minWidth: 240 }}
                        value={run?.id}
                        options={runs.map((item) => ({
                          value: item.id,
                          label: `${tr(
                            `status.${item.status}`,
                          )} / ${formatServerDateTime(
                            item.created_at,
                            timezone,
                          )} / v${item.version}`,
                        }))}
                        onChange={(id) => {
                          setRun(runs.find((item) => item.id === id) || null);
                          setOffset(0);
                        }}
                      />
                      <Button
                        size="small"
                        onClick={() =>
                          void attempt(async () =>
                            setRuns((await api.runs(view.graph_id)).items),
                          )
                        }
                      >
                        {tr("refresh")}
                      </Button>
                      {run && (
                        <>
                          <Button
                            size="small"
                            onClick={() => setShowRun((value) => !value)}
                          >
                            {readonly ? tr("editDraft") : tr("viewRun")}
                          </Button>
                          <Tag>{tr(`status.${run.status}`)}</Tag>
                          <span>
                            {run.steps}/{run.max_steps} {tr("steps")}
                          </span>
                          <Button
                            size="small"
                            onClick={() => runControl("pause")}
                          >
                            {tr("pause")}
                          </Button>
                          <Button
                            size="small"
                            onClick={() => runControl("resume")}
                          >
                            {tr("resume")}
                          </Button>
                          <Button
                            size="small"
                            onClick={() => {
                              setSteps(Math.min(1000, run.max_steps + 100));
                              setBudgetOpen(true);
                            }}
                          >
                            {tr("extendBudget")}
                          </Button>
                          <Button
                            size="small"
                            danger
                            onClick={() => runControl("cancel")}
                          >
                            {tr("cancelRun")}
                          </Button>
                          <Button
                            size="small"
                            danger
                            onClick={() =>
                              Modal.confirm({
                                title: tr("cancelJobs"),
                                content: tr("cancelJobsHelp"),
                                onOk: async () => {
                                  const result = await api.cancelJobs(run.id);
                                  setRun(result.run);
                                  setCancellationReceipts(result.jobs);
                                },
                              })
                            }
                          >
                            {tr("cancelJobs")}
                          </Button>
                        </>
                      )}
                    </div>
                    {run?.error && <Alert type="warning" message={run.error} />}
                    {!run ? (
                      <p>{tr("runsHelp")}</p>
                    ) : (
                      <>
                        <ol className="wg-timeline">
                          {timeline.map((item) => (
                            <li key={item.id}>
                              <button
                                className={`state-${item.status}`}
                                onClick={() =>
                                  void attempt(async () =>
                                    setDetail(await api.inspect(item.id)),
                                  )
                                }
                              >
                                <span>{item.ordinal}</span>
                                <strong>
                                  {(runDefinition || draft).nodes.find(
                                    (n) => n.id === item.node_id,
                                  )?.label || item.node_id}
                                </strong>
                                <small>{tr(`status.${item.status}`)}</small>
                              </button>
                            </li>
                          ))}
                        </ol>
                        <Pagination
                          size="small"
                          pageSize={100}
                          current={offset / 100 + 1}
                          total={timelineTotal}
                          onChange={(page) => setOffset((page - 1) * 100)}
                        />
                      </>
                    )}
                  </>
                )}
              </section>
            </>
          ) : (
            <div className="wg-empty">
              <GitBranch size={48} />
              <h2>{tr("emptyTitle")}</h2>
              <p>{tr("emptyHelp")}</p>
              <Space wrap>
                <Button type="primary" onClick={create}>
                  {tr("create")}
                </Button>
                {(["daily", "iteration", "event"] as const).map((value) => (
                  <Button
                    key={value}
                    onClick={() => {
                      setTemplate(value);
                      create();
                    }}
                  >
                    {tr(`template.${value}`)}
                  </Button>
                ))}
              </Space>
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={tr("selectOrCreate")}
              />
            </div>
          )}
          {busy && (
            <div className="wg-busy">
              <Spin />
            </div>
          )}
        </main>
      </div>
      <Drawer
        title={tr("library")}
        open={libraryOpen}
        onClose={() => setLibraryOpen(false)}
        width={300}
        className="wg-library-drawer"
        extra={
          <Button type="text" icon={<Plus size={16} />} onClick={create}>
            {tr("create")}
          </Button>
        }
      >
        {" "}
        <aside className="wg-library">
          <h2>
            <GitBranch size={18} />
            {tr("library")}
          </h2>
          {catalog.map((item) => (
            <button
              className={view?.graph_id === item.graph_id ? "active" : ""}
              key={item.graph_id}
              onClick={() => load(item.graph_id)}
            >
              <strong>{item.name}</strong>
              <small>
                {item.published_revision
                  ? `${tr("published")} v${item.published_revision}`
                  : tr("draft")}
              </small>
            </button>
          ))}
          {!catalog.length && <p>{tr("libraryEmpty")}</p>}
          {catalogTotal > 50 && (
            <Pagination
              simple
              pageSize={50}
              current={catalogOffset / 50 + 1}
              total={catalogTotal}
              onChange={(page) => setCatalogOffset((page - 1) * 50)}
            />
          )}
        </aside>
      </Drawer>
      {draft && view && (
        <Drawer
          title={tr("settings")}
          open={settingsOpen}
          onClose={() => setSettingsOpen(false)}
          width={440}
          className="wg-settings-drawer"
        >
          <div className="wg-settings-actions">
            <h3>{tr("workflowActions")}</h3>
            <Space wrap>
              <Button
                aria-label={tr("undo")}
                icon={<Undo2 size={16} />}
                disabled={readonly || !past.length}
                onClick={undo}
              >
                {tr("undo")}
              </Button>
              <Button
                aria-label={tr("redo")}
                icon={<Redo2 size={16} />}
                disabled={readonly || !future.length}
                onClick={redo}
              >
                {tr("redo")}
              </Button>
              <Button
                icon={<Upload size={15} />}
                onClick={() => file.current?.click()}
              >
                {tr("import")}
              </Button>
              <Button icon={<Download size={15} />} onClick={exportGraph}>
                {tr("export")}
              </Button>
              <Button
                disabled={busy}
                icon={<Save size={15} />}
                onClick={() => void attempt(save)}
              >
                {tr("save")}
              </Button>
              <Button
                disabled={busy}
                onClick={() =>
                  void attempt(async () => {
                    const saved = await save();
                    if (saved) {
                      install(await api.publish(view.graph_id, saved.revision));
                      await reloadList();
                    }
                  })
                }
              >
                {tr("publish")}
              </Button>
              <Button
                type="primary"
                disabled={busy || !view.published_revision}
                icon={<Play size={15} />}
                onClick={() => {
                  setVariables({});
                  setRequestId(crypto.randomUUID());
                  setRunOpen(true);
                }}
              >
                {tr("start")}
              </Button>
            </Space>
          </div>
          <Inspector graph={draft} onChange={changed} agents={agents} tr={tr} />
          <div className="wg-settings-utilities">
            <h3>{tr("management")}</h3>{" "}
            <div className="wg-statusbar">
              <span>
                {draft.nodes.length} {tr("nodes")} / {draft.edges.length}{" "}
                {tr("connections")}
              </span>
              <Space>
                <Button
                  size="small"
                  onClick={() =>
                    void attempt(async () =>
                      setIssues(await api.validate(draft)),
                    )
                  }
                >
                  {tr("validate")}
                </Button>
                <Button
                  size="small"
                  danger
                  icon={<Trash2 size={14} />}
                  disabled={readonly || !selected}
                  onClick={remove}
                >
                  {tr("delete")}
                </Button>
                <Button
                  size="small"
                  onClick={() =>
                    void attempt(async () =>
                      setCapability(await api.capability(view.graph_id)),
                    )
                  }
                >
                  {tr("callback")}
                </Button>
                <Button
                  size="small"
                  danger
                  icon={<Archive size={14} />}
                  onClick={() =>
                    Modal.confirm({
                      title: tr("archive"),
                      onOk: async () => {
                        await api.archive(view.graph_id, view.revision);
                        setView(null);
                        setDraft(null);
                        setRun(null);
                        await reloadList();
                      },
                    })
                  }
                >
                  {tr("archive")}
                </Button>
              </Space>
            </div>
          </div>
        </Drawer>
      )}
      <input
        ref={file}
        type="file"
        accept="application/json,.json"
        hidden
        onChange={(event) => {
          const chosen = event.target.files?.[0];
          event.target.value = "";
          if (!chosen) return;
          void attempt(async () => {
            if (chosen.size > 512 * 1024) throw new Error(tr("fileTooLarge"));
            const definition = JSON.parse(
              await chosen.text(),
            ) as GraphDefinition;
            const validation = await api.normalize(definition);
            confirmDiscard(() => {
              if (draft) changed(validation.definition);
              setIssues(validation.issues);
            });
          });
        }}
      />
      <Modal
        title={tr("create")}
        open={createOpen}
        confirmLoading={busy}
        onCancel={() => setCreateOpen(false)}
        onOk={() =>
          void attempt(async () => {
            const definition = example(template, agents[0]?.agent_id || "");
            install(await api.save(newId, 0, definition));
            setCreateOpen(false);
            setLibraryOpen(false);
            setSettingsOpen(false);
            setRun(null);
            setRuns([]);
            await reloadList();
          })
        }
      >
        <Form layout="vertical">
          <Form.Item label={tr("graphId")}>
            <Input value={newId} onChange={(e) => setNewId(e.target.value)} />
          </Form.Item>
          <Form.Item label={tr("templateLabel")}>
            <Select
              value={template}
              onChange={setTemplate}
              options={["blank", "daily", "iteration", "event"].map(
                (value) => ({ value, label: tr(`template.${value}`) }),
              )}
            />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title={tr("start")}
        open={runOpen}
        onCancel={() => setRunOpen(false)}
        confirmLoading={busy}
        onOk={() =>
          view &&
          void attempt(async () => {
            const value = await api.start(view.graph_id, variables, requestId);
            setRun(value);
            setRunsExpanded(true);
            setSettingsOpen(false);
            setOffset(0);
            setRuns((await api.runs(view.graph_id)).items);
            setRunOpen(false);
          })
        }
      >
        {dirty && <Alert type="warning" message={tr("startPublished")} />}
        <p>{tr("startHelp")}</p>
        <JsonField
          label={tr("variables")}
          value={variables}
          onChange={(value) => setVariables(value as Record<string, unknown>)}
        />
      </Modal>
      <Modal
        title={tr("extendBudget")}
        open={budgetOpen}
        onCancel={() => setBudgetOpen(false)}
        onOk={() =>
          run &&
          void attempt(async () => {
            setRun(
              await api.control(run.id, "resume", {
                max_steps: steps,
                extra_seconds: seconds,
              }),
            );
            setBudgetOpen(false);
          })
        }
      >
        <Form layout="vertical">
          <Form.Item label={tr("max_steps")}>
            <InputNumber
              min={1}
              max={1000}
              value={steps}
              onChange={(v) => setSteps(v || 200)}
            />
          </Form.Item>
          <Form.Item label={tr("extra_seconds")}>
            <InputNumber
              min={60}
              max={2592000}
              value={seconds}
              onChange={(v) => setSeconds(v || 86400)}
            />
          </Form.Item>
        </Form>
        <p>{tr("retainHelp")}</p>
      </Modal>
      <Drawer
        title={tr("activation")}
        open={!!detail}
        onClose={() => setDetail(null)}
        width={600}
      >
        {detail && (
          <>
            <Tag>{tr(`status.${detail.status}`)}</Tag>
            <h3>{detail.node_id}</h3>
            {detail.error && <Alert type="warning" message={detail.error} />}
            {detail.before?.thread_id && (
              <a
                href={`/chat/${encodeURIComponent(
                  detail.before.agent_id,
                )}/${encodeURIComponent(detail.before.thread_id)}`}
                target="_blank"
                rel="noreferrer"
              >
                {tr("openConversation")}
              </a>
            )}
            <Space wrap>
              <Button
                onClick={() =>
                  void attempt(async () => {
                    setDetail(await api.reconcile(detail.id));
                    message.success(tr("reconciled"));
                  })
                }
              >
                {tr("reconcile")}
              </Button>
              <Button
                danger
                onClick={() =>
                  Modal.confirm({
                    title: tr("retry"),
                    content: tr("retryHelp"),
                    onOk: async () => {
                      setRun(await api.retry(detail.id));
                      setDetail(null);
                    },
                  })
                }
              >
                {tr("retry")}
              </Button>
            </Space>
            {["input", "output", "before", "after", "evidence"].map((key) => (
              <section key={key}>
                <h4>{tr(key)}</h4>
                <pre className="wg-detail-json">
                  {JSON.stringify(detail[key as keyof Activation], null, 2)}
                </pre>
              </section>
            ))}
          </>
        )}
      </Drawer>
      <Modal
        title={tr("callback")}
        open={!!capability}
        onCancel={() => setCapability(null)}
        footer={
          <Button
            danger
            onClick={() =>
              view &&
              void attempt(async () =>
                setCapability(await api.capability(view.graph_id, true)),
              )
            }
          >
            {tr("revoke")}
          </Button>
        }
      >
        {capability && (
          <>
            <p>{tr("callbackHelp")}</p>
            <Input.TextArea
              readOnly
              rows={7}
              value={JSON.stringify(
                {
                  url: capability.callback_url,
                  headers: { "X-Octop-Graph-Token": capability.token },
                  body: { event_id: "unique-event-id", data: {} },
                },
                null,
                2,
              )}
            />
          </>
        )}
      </Modal>
      <Modal
        title={tr("cancellationReceipts")}
        open={!!cancellationReceipts}
        footer={null}
        onCancel={() => setCancellationReceipts(null)}
      >
        <p>{tr("cancellationReceiptHelp")}</p>
        <pre className="wg-detail-json">
          {JSON.stringify(cancellationReceipts, null, 2)}
        </pre>
      </Modal>
    </section>
  );
}
