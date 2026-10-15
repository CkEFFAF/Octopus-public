import React, {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Dropdown, Spin, Tooltip } from "antd";
import type { MenuProps } from "antd";
import {
  BookOpen,
  Check,
  FilePen,
  FolderOpen,
  GitBranch,
  ListTodo,
  Monitor,
  Activity,
  Globe,
  Plus,
  Puzzle,
  RefreshCw,
  Terminal,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import BrowserWorkspace, {
  type PanelMode,
} from "../../../components/BrowserWorkspace";
import ChatDockPanelShell, {
  CHAT_DOCK_POPUP_MENU_Z,
} from "../../../components/BrowserWorkspace/ChatDockPanelShell";
import type { DisplayEnvironment } from "../../../api/types/browser";
import { useCurrentUser } from "../../../hooks/useCurrentUser";
import { resolveBrowserProfile } from "../../../utils/browserProfile";
import type { DockTab, DockTabId } from "../hooks/useChatDockPanel";
import { dockFileBasename } from "../utils/dockFilePath";
import styles from "../index.module.less";
import WorkspaceDrawer from "../../Agent/Workspace/components/WorkspaceDrawer";
import ChatDockFileList from "./ChatDockFileList";
import FilePanelContent from "./FilePanelContent";
import KnowledgeCitationPanelContent from "./KnowledgeCitationPanelContent";
import ChatDockToolUiContent from "./ChatDockToolUiContent";
import ChatDockGit from "./ChatDockGit";
import ChatDockContext from "./ChatDockContext";
import ExecutionWorkbench from "./ExecutionWorkbench";

const TerminalPage = lazy(() => import("../../Control/Terminal"));

export type ChatDockAddTabHandlers = {
  onOpenWorkspace?: () => void;
  onOpenBrowser?: () => void;
  onOpenTerminal?: () => void;
  onOpenGit?: () => void;
  onOpenContext?: () => void;
  onOpenJobs?: () => void;
  onOpenDesktop?: () => void;
  onOpenPlan?: () => void;
  onOpenTrajectory?: () => void;
  onOpenFiles?: () => void;
  workspaceDisabled?: boolean;
  workspaceDisabledHint?: string;
};

type AddTabKey =
  | "workspace"
  | "files"
  | "browser"
  | "terminal"
  | "git"
  | "context"
  | "jobs"
  | "desktop"
  | "plan"
  | "trajectory";

interface ChatDockPanelProps {
  mode: PanelMode;
  onModeChange: (mode: PanelMode) => void;
  onClose: () => void;
  style?: React.CSSProperties;
  agentId: string;
  filePaths: Array<string | { path: string; agentId?: string }>;
  agentNameById?: Record<string, string>;
  openTabs: DockTab[];
  activeTabId: DockTabId | null;
  onSelectTab: (id: DockTabId) => void;
  onCloseTab: (id: DockTabId) => void;
  onOpenFile: (path: string, agentId?: string | null) => void;
  browserEnvironment?: DisplayEnvironment;
  /** When set, Chat dock browser talks to the peer harness via Bridge. */
  bridgeConnectionId?: string | null;
  threadId?: string | null;
  isStreamingTurn?: boolean;
  /**
   * False while the chat dock shell is closed but keep-alive mounted.
   * Mirrors Workbench ``isVisible`` so terminal does not treat hide as a
   * fresh first visit.
   */
  surfaceVisible?: boolean;
  /** Open workspace / browser / terminal / file-list tabs from the title-bar +. */
  addTab?: ChatDockAddTabHandlers;
}

function hasOpenKind(tabs: readonly DockTab[], kind: DockTab["kind"]): boolean {
  return tabs.some(
    (tab) =>
      tab.kind === kind || (tab.kind === "execution" && tab.surface === kind),
  );
}

/** Title-bar + control: open dock tabs that the float rail normally exposes. */
const DockAddTabButton: React.FC<{
  mode: PanelMode;
  addTab: ChatDockAddTabHandlers;
  openTabs: readonly DockTab[];
  menuOpen: boolean;
  onMenuOpenChange: (open: boolean) => void;
}> = ({ mode, addTab, openTabs, menuOpen, onMenuOpenChange }) => {
  const { t } = useTranslation();

  const items: MenuProps["items"] = useMemo(() => {
    const check = (kind: DockTab["kind"]) =>
      hasOpenKind(openTabs, kind) ? <Check size={14} /> : undefined;
    const next: NonNullable<MenuProps["items"]> = [];
    if (addTab.onOpenWorkspace) {
      next.push({
        key: "workspace",
        label: t("chat.openWorkspace", "工作区"),
        icon: <FolderOpen size={14} />,
        disabled: addTab.workspaceDisabled,
        title: addTab.workspaceDisabled
          ? addTab.workspaceDisabledHint
          : undefined,
        extra: check("workspace"),
      });
    }
    if (addTab.onOpenFiles) {
      next.push({
        key: "files",
        label: t("chat.dockFileList", "文件变更"),
        icon: <FilePen size={14} />,
        extra: check("files"),
      });
    }
    if (addTab.onOpenBrowser) {
      next.push({
        key: "browser",
        label: t("chat.remoteBrowserTitle", "远程浏览器"),
        icon: <Globe size={14} />,
        extra: check("browser"),
      });
    }
    if (addTab.onOpenTerminal) {
      next.push({
        key: "terminal",
        label: t("chat.dockTerminalTitle", "终端"),
        icon: <Terminal size={14} />,
        extra: check("terminal"),
      });
    }
    if (addTab.onOpenGit) {
      next.push({
        key: "git",
        label: t("chat.git.title"),
        icon: <GitBranch size={14} />,
        extra: check("git"),
      });
    }
    if (addTab.onOpenPlan) {
      next.push({
        key: "plan",
        label: t("chat.openPlanFile"),
        icon: <ListTodo size={14} />,
      });
    }
    if (addTab.onOpenContext) {
      next.push({
        key: "context",
        label: t("chat.contextInspect.title"),
        icon: <Activity size={14} />,
        extra: check("context"),
      });
    }
    if (addTab.onOpenJobs) {
      next.push({
        key: "jobs",
        label: t("chat.execution.jobs"),
        icon: <Activity size={14} />,
      });
    }
    if (addTab.onOpenDesktop) {
      next.push({
        key: "desktop",
        label: t("remoteDesktopHub.title"),
        icon: <Monitor size={14} />,
      });
    }
    if (addTab.onOpenTrajectory) {
      next.push({
        key: "trajectory",
        label: t("chat.trajectoryTitle"),
        icon: <Activity size={14} />,
      });
    }
    return next;
  }, [addTab, openTabs, t]);

  const onClick = useCallback<NonNullable<MenuProps["onClick"]>>(
    ({ key }) => {
      const openers: Record<AddTabKey, (() => void) | undefined> = {
        workspace: addTab.onOpenWorkspace,
        files: addTab.onOpenFiles,
        browser: addTab.onOpenBrowser,
        terminal: addTab.onOpenTerminal,
        git: addTab.onOpenGit,
        context: addTab.onOpenContext,
        jobs: addTab.onOpenJobs,
        desktop: addTab.onOpenDesktop,
        plan: addTab.onOpenPlan,
        trajectory: addTab.onOpenTrajectory,
      };
      openers[key as AddTabKey]?.();
    },
    [addTab],
  );

  if (!items?.length) return null;

  const label = t("chat.dockAddTab", "添加面板");

  return (
    <Dropdown
      menu={{ items, onClick }}
      trigger={["click"]}
      placement="bottomLeft"
      getPopupContainer={() => document.body}
      open={menuOpen}
      onOpenChange={onMenuOpenChange}
      overlayStyle={
        mode === "popup" ? { zIndex: CHAT_DOCK_POPUP_MENU_Z } : undefined
      }
    >
      <Tooltip title={label}>
        <button
          type="button"
          className={styles.dockTabAdd}
          onPointerDown={(e) => e.stopPropagation()}
          aria-label={label}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
        >
          <Plus size={14} strokeWidth={2} />
        </button>
      </Tooltip>
    </Dropdown>
  );
};

/**
 * Tabbed dock shell: workspace / file list / file viewers / browser / terminal.
 * Bodies stay mounted after first open so streams / editors survive tab switches.
 */
const ChatDockPanel: React.FC<ChatDockPanelProps> = ({
  mode,
  onModeChange,
  onClose,
  style,
  agentId,
  filePaths,
  agentNameById,
  openTabs,
  activeTabId,
  onSelectTab,
  onCloseTab,
  onOpenFile,
  browserEnvironment = "desktop",
  bridgeConnectionId = null,
  threadId = null,
  isStreamingTurn = false,
  surfaceVisible = true,
  addTab,
}) => {
  const { t } = useTranslation();
  const currentUser = useCurrentUser();
  const [addTabMenuOpen, setAddTabMenuOpen] = useState(false);
  const [workspaceMounted, setWorkspaceMounted] = useState(
    openTabs.some((tab) => tab.kind === "workspace"),
  );
  const [browserMounted, setBrowserMounted] = useState(
    openTabs.some((tab) => tab.kind === "browser"),
  );
  const [terminalMounted, setTerminalMounted] = useState(
    openTabs.some((tab) => tab.kind === "terminal"),
  );
  const [mountedFileTabs, setMountedFileTabs] = useState<
    Extract<DockTab, { kind: "file" }>[]
  >(() => openTabs.filter((tab) => tab.kind === "file"));
  const [mountedKnowledgeTabs, setMountedKnowledgeTabs] = useState<
    Extract<DockTab, { kind: "knowledge" }>[]
  >(() => openTabs.filter((tab) => tab.kind === "knowledge"));
  const [mountedToolUiCallIds, setMountedToolUiCallIds] = useState<string[]>(
    () =>
      openTabs.filter((tab) => tab.kind === "toolUi").map((tab) => tab.callId),
  );
  const [fileActionsById, setFileActionsById] = useState<
    Record<string, ReactNode>
  >({});
  const [knowledgeActionsById, setKnowledgeActionsById] = useState<
    Record<string, ReactNode>
  >({});
  const browserRefreshRef = useRef<(() => void) | null>(null);
  const fileActionsHandlersRef = useRef<
    Record<string, (actions: ReactNode | null) => void>
  >({});
  const knowledgeActionsHandlersRef = useRef<
    Record<string, (actions: ReactNode | null) => void>
  >({});

  useEffect(() => {
    const hasWorkspace = openTabs.some((tab) => tab.kind === "workspace");
    const hasBrowser = openTabs.some((tab) => tab.kind === "browser");
    const hasTerminal = openTabs.some((tab) => tab.kind === "terminal");
    setWorkspaceMounted(hasWorkspace);
    setBrowserMounted(hasBrowser);
    setTerminalMounted(hasTerminal);
    const openFileById = new Map(
      openTabs
        .filter(
          (tab): tab is Extract<DockTab, { kind: "file" }> =>
            tab.kind === "file",
        )
        .map((tab) => [tab.id, tab]),
    );
    const openKnowledgeById = new Map(
      openTabs
        .filter(
          (tab): tab is Extract<DockTab, { kind: "knowledge" }> =>
            tab.kind === "knowledge",
        )
        .map((tab) => [tab.id, tab]),
    );
    const openToolUiCallIds = new Set(
      openTabs.filter((tab) => tab.kind === "toolUi").map((tab) => tab.callId),
    );
    setMountedFileTabs((prev) => {
      const next = prev
        .filter((tab) => openFileById.has(tab.id))
        .map((tab) => openFileById.get(tab.id) ?? tab);
      let changed =
        next.length !== prev.length || next.some((tab, i) => tab !== prev[i]);
      for (const tab of openFileById.values()) {
        if (!next.some((row) => row.id === tab.id)) {
          next.push(tab);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
    setMountedKnowledgeTabs((prev) => {
      const next = prev
        .filter((tab) => openKnowledgeById.has(tab.id))
        .map((tab) => openKnowledgeById.get(tab.id) ?? tab);
      let changed =
        next.length !== prev.length || next.some((tab, i) => tab !== prev[i]);
      for (const tab of openKnowledgeById.values()) {
        if (!next.some((row) => row.id === tab.id)) {
          next.push(tab);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
    setMountedToolUiCallIds((prev) => {
      const next = prev.filter((callId) => openToolUiCallIds.has(callId));
      let changed = next.length !== prev.length;
      for (const callId of openToolUiCallIds) {
        if (!next.includes(callId)) {
          next.push(callId);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
    setFileActionsById((prev) => {
      let changed = false;
      const next: Record<string, ReactNode> = {};
      for (const id of Object.keys(prev)) {
        if (openFileById.has(id)) {
          next[id] = prev[id];
        } else {
          changed = true;
          delete fileActionsHandlersRef.current[id];
        }
      }
      return changed ? next : prev;
    });
    setKnowledgeActionsById((prev) => {
      let changed = false;
      const next: Record<string, ReactNode> = {};
      for (const id of Object.keys(prev)) {
        if (openKnowledgeById.has(id)) {
          next[id] = prev[id];
        } else {
          changed = true;
          delete knowledgeActionsHandlersRef.current[id];
        }
      }
      return changed ? next : prev;
    });
  }, [openTabs]);

  const handleBrowserRefreshReady = useCallback((refresh: () => void) => {
    browserRefreshRef.current = refresh;
  }, []);

  const getFileActionsHandler = useCallback((tabId: string) => {
    const existing = fileActionsHandlersRef.current[tabId];
    if (existing) return existing;
    const handler = (actions: ReactNode | null) => {
      setFileActionsById((prev) => {
        if (actions == null) {
          if (!(tabId in prev)) return prev;
          const next = { ...prev };
          delete next[tabId];
          return next;
        }
        if (prev[tabId] === actions) return prev;
        return { ...prev, [tabId]: actions };
      });
    };
    fileActionsHandlersRef.current[tabId] = handler;
    return handler;
  }, []);

  const getKnowledgeActionsHandler = useCallback((tabId: string) => {
    const existing = knowledgeActionsHandlersRef.current[tabId];
    if (existing) return existing;
    const handler = (actions: ReactNode | null) => {
      setKnowledgeActionsById((prev) => {
        if (actions == null) {
          if (!(tabId in prev)) return prev;
          const next = { ...prev };
          delete next[tabId];
          return next;
        }
        if (prev[tabId] === actions) return prev;
        return { ...prev, [tabId]: actions };
      });
    };
    knowledgeActionsHandlersRef.current[tabId] = handler;
    return handler;
  }, []);

  const sessionId = bridgeConnectionId
    ? null
    : resolveBrowserProfile(currentUser?.id);
  const activeTab =
    openTabs.find((tab) => tab.id === activeTabId) ?? openTabs[0] ?? null;
  const terminalVisible = surfaceVisible && activeTab?.kind === "terminal";

  const tabBar = (
    <div className={styles.dockTabBar}>
      <div className={styles.dockTabs} role="tablist">
        {openTabs.map((tab) => {
          const selected = tab.id === (activeTab?.id ?? null);
          const label =
            tab.kind === "files" ? (
              <>
                <FolderOpen size={16} strokeWidth={2} aria-hidden />
                <span>{t("chat.dockFileList", "文件变更")}</span>
              </>
            ) : tab.kind === "workspace" ? (
              <>
                <FolderOpen size={16} strokeWidth={2} aria-hidden />
                <span>{t("chat.openWorkspace", "工作区")}</span>
              </>
            ) : tab.kind === "browser" ? (
              <>
                <Globe size={16} strokeWidth={2} aria-hidden />
                <span>{t("chat.remoteBrowserTitle", "远程浏览器")}</span>
              </>
            ) : tab.kind === "terminal" ? (
              <>
                <Terminal size={16} strokeWidth={2} aria-hidden />
                <span>{t("chat.dockTerminalTitle", "终端")}</span>
              </>
            ) : tab.kind === "git" ? (
              <>
                <GitBranch size={16} strokeWidth={2} aria-hidden />
                <span>{t("chat.git.title")}</span>
              </>
            ) : tab.kind === "context" ? (
              <>
                <Activity size={16} aria-hidden />
                <span>{t("chat.contextInspect.title")}</span>
              </>
            ) : tab.kind === "execution" ? (
              <>
                <Monitor size={16} aria-hidden />
                <span
                  title={`${
                    tab.context.device_id ?? t("devices.localExecution")
                  } · ${tab.context.working_dir ?? ""}`}
                >
                  {t(
                    tab.surface === "git"
                      ? "chat.git.title"
                      : tab.surface === "jobs"
                      ? "chat.execution.jobs"
                      : tab.surface === "terminal"
                      ? "chat.dockTerminalTitle"
                      : tab.surface === "browser"
                      ? "chat.dockBrowserTitle"
                      : tab.surface === "desktop"
                      ? "remoteDesktopHub.title"
                      : "chat.openWorkspace",
                  )}{" "}
                  ·{" "}
                  {tab.context.working_dir
                    ?.split(/[\\/]/)
                    .filter(Boolean)
                    .pop() ??
                    tab.context.device_id?.slice(-6) ??
                    t("devices.localExecution")}
                </span>
              </>
            ) : tab.kind === "toolUi" ? (
              <>
                <Puzzle size={16} strokeWidth={2} aria-hidden />
                <span title={tab.title ?? tab.toolName}>
                  {tab.title ??
                    tab.toolName ??
                    t("chat.dockToolUiTitle", "Plugin tool")}
                </span>
              </>
            ) : tab.kind === "knowledge" ? (
              <>
                <BookOpen size={16} strokeWidth={2} aria-hidden />
                <span title={tab.citation.filename}>
                  {tab.citation.filename || t("chat.citationPreview")}
                </span>
              </>
            ) : (
              <>
                <FilePen size={16} strokeWidth={2} aria-hidden />
                <span
                  title={
                    tab.agentId && tab.agentId !== agentId
                      ? `${tab.path} · ${
                          agentNameById?.[tab.agentId] || tab.agentId
                        }`
                      : tab.path
                  }
                >
                  {dockFileBasename(tab.path)}
                  {tab.agentId &&
                  tab.agentId !== agentId &&
                  (agentNameById?.[tab.agentId] || tab.agentId)
                    ? ` · ${agentNameById?.[tab.agentId] || tab.agentId}`
                    : ""}
                </span>
              </>
            );
          return (
            <div
              key={tab.id}
              className={`${styles.dockTab} ${
                selected ? styles.dockTabActive : ""
              }`}
              role="tab"
              aria-selected={selected}
            >
              <button
                type="button"
                className={styles.dockTabLabel}
                onClick={() => onSelectTab(tab.id)}
              >
                {label}
              </button>
              <button
                type="button"
                className={styles.dockTabClose}
                onClick={(e) => {
                  e.stopPropagation();
                  onCloseTab(tab.id);
                }}
                aria-label={t("common.close", "关闭")}
              >
                <X size={12} strokeWidth={2} />
              </button>
            </div>
          );
        })}
      </div>
      {addTab ? (
        <DockAddTabButton
          mode={mode}
          addTab={addTab}
          openTabs={openTabs}
          menuOpen={addTabMenuOpen}
          onMenuOpenChange={setAddTabMenuOpen}
        />
      ) : null}
    </div>
  );

  const toolbarActions = useMemo(() => {
    if (activeTab?.kind === "browser") {
      return (
        <Tooltip title={t("browserWorkspace.reconnect")}>
          <button
            type="button"
            className={styles.fileModalIconBtn}
            onClick={() => browserRefreshRef.current?.()}
            aria-label={t("browserWorkspace.reconnect")}
          >
            <RefreshCw size={16} strokeWidth={2} />
          </button>
        </Tooltip>
      );
    }
    if (activeTab?.kind === "file") {
      return fileActionsById[activeTab.id] ?? null;
    }
    if (activeTab?.kind === "knowledge") {
      return knowledgeActionsById[activeTab.id] ?? null;
    }
    return null;
  }, [activeTab, fileActionsById, knowledgeActionsById, t]);

  return (
    <ChatDockPanelShell
      mode={mode}
      onModeChange={onModeChange}
      onClose={onClose}
      style={style}
      title={tabBar}
      toolbarActions={toolbarActions}
      overlayMenuOpen={addTabMenuOpen}
    >
      <div className={styles.dockTabBodies}>
        {openTabs
          .filter(
            (tab): tab is Extract<DockTab, { kind: "execution" }> =>
              tab.kind === "execution",
          )
          .map((tab) => (
            <div
              key={tab.id}
              className={styles.dockTabBody}
              style={{ display: activeTab?.id === tab.id ? "flex" : "none" }}
            >
              <ExecutionWorkbench
                context={tab.context}
                surface={tab.surface}
                initialFilePath={tab.initialFilePath}
                visible={surfaceVisible && activeTab?.id === tab.id}
              />
            </div>
          ))}
        {activeTab?.kind === "context" && (
          <div className={styles.dockTabBody}>
            <ChatDockContext
              agentId={agentId}
              threadId={threadId}
              live={isStreamingTurn}
            />
          </div>
        )}
        {openTabs.some((tab) => tab.kind === "files") && (
          <div
            className={styles.dockTabBody}
            hidden={activeTab?.kind !== "files"}
            style={{
              display: activeTab?.kind === "files" ? "flex" : "none",
            }}
          >
            <ChatDockFileList
              agentId={agentId}
              filePaths={filePaths}
              agentNameById={agentNameById}
              onOpenFile={onOpenFile}
            />
          </div>
        )}

        {mountedFileTabs.map((tab) => {
          const isActive =
            activeTab?.kind === "file" && activeTab.id === tab.id;
          const fileAgent = tab.agentId || agentId;
          return (
            <div
              key={tab.id}
              className={styles.dockTabBody}
              hidden={!isActive}
              style={{ display: isActive ? "flex" : "none" }}
            >
              <FilePanelContent
                agentId={fileAgent}
                filePath={tab.path}
                onActionsChange={getFileActionsHandler(tab.id)}
              />
            </div>
          );
        })}

        {openTabs.some((tab) => tab.kind === "git") && (
          <div
            className={styles.dockTabBody}
            hidden={activeTab?.kind !== "git"}
            style={{ display: activeTab?.kind === "git" ? "flex" : "none" }}
          >
            <ChatDockGit agentId={agentId} />
          </div>
        )}

        {mountedKnowledgeTabs.map((tab) => {
          const isActive =
            activeTab?.kind === "knowledge" && activeTab.id === tab.id;
          return (
            <div
              key={tab.id}
              className={styles.dockTabBody}
              hidden={!isActive}
              style={{ display: isActive ? "flex" : "none" }}
            >
              <KnowledgeCitationPanelContent
                citation={tab.citation}
                onActionsChange={getKnowledgeActionsHandler(tab.id)}
              />
            </div>
          );
        })}

        {workspaceMounted && (
          <div
            className={styles.dockTabBody}
            hidden={activeTab?.kind !== "workspace"}
            style={{
              display: activeTab?.kind === "workspace" ? "flex" : "none",
            }}
          >
            <WorkspaceDrawer
              agentId={agentId}
              open
              onClose={() => onCloseTab("workspace")}
              embedded
            />
          </div>
        )}

        {browserMounted && (
          <div
            className={styles.dockTabBody}
            hidden={activeTab?.kind !== "browser"}
            style={{
              display: activeTab?.kind === "browser" ? "flex" : "none",
            }}
          >
            <BrowserWorkspace
              sessionId={sessionId}
              environment={browserEnvironment}
              bridgeConnectionId={bridgeConnectionId}
              hideHeaderRefresh
              style={{ flex: 1, minHeight: 0 }}
              onRefreshReady={handleBrowserRefreshReady}
            />
          </div>
        )}

        {terminalMounted && (
          <div
            className={styles.dockTabBody}
            style={{ display: terminalVisible ? "flex" : "none" }}
            aria-hidden={!terminalVisible}
          >
            <Suspense
              fallback={
                <div className={styles.dockTerminalLoading}>
                  <Spin size="small" />
                </div>
              }
            >
              <TerminalPage embedded isVisible={terminalVisible} />
            </Suspense>
          </div>
        )}

        {mountedToolUiCallIds.map((callId) => {
          const isActive =
            activeTab?.kind === "toolUi" && activeTab.callId === callId;
          return (
            <div
              key={callId}
              className={styles.dockTabBody}
              hidden={!isActive}
              style={{ display: isActive ? "flex" : "none" }}
            >
              <ChatDockToolUiContent
                threadId={threadId}
                callId={callId}
                agentId={agentId}
                isStreamingTurn={isStreamingTurn}
              />
            </div>
          );
        })}
      </div>
    </ChatDockPanelShell>
  );
};

export default ChatDockPanel;
