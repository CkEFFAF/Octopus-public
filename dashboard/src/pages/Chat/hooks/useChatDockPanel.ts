import { useCallback, useEffect, useRef, useState } from "react";
import type { PanelMode } from "../../../components/BrowserWorkspace";
import {
  executionApi,
  type ExecutionContext,
} from "../../../api/modules/execution";
import {
  executionScope,
  getExecutionSelection,
  targetFields,
  executionSelectionReady,
} from "./deviceTarget";
import { useTranslation } from "react-i18next";
import { showApiError } from "../../../utils/showApiToast";
import {
  canonicalizeDockFilePath,
  dockFileTabId,
  isHostAbsolutePath,
  normalizeDockFilePath,
} from "../utils/dockFilePath";
import type { KnowledgeCitation } from "../../../utils/parseKnowledgeCitations";
import { dockKnowledgeTabId } from "../utils/dockKnowledgeTabId";
import { dockToolUiTabId } from "../utils/dockToolUiTabId";
import { usePanelResize, type PanelSizes } from "./usePanelResize";

const PANEL_MODE_KEY = "octop:chat-dock:mode";
const PANEL_SIZE_KEY = "octop:chat-dock:size";
/** Legacy keys — read once for migration. */
const LEGACY_FILE_MODE_KEY = "octop:file-panel:mode";
const LEGACY_BROWSER_MODE_KEY = "octop:browser-panel:mode";
const LEGACY_FILE_SIZE_KEY = "octop:file-panel:size";
const LEGACY_BROWSER_SIZE_KEY = "octop:browser-panel:size";

export type DockTab =
  | { id: "files"; kind: "files" }
  | { id: "workspace"; kind: "workspace" }
  | { id: "browser"; kind: "browser" }
  | { id: "terminal"; kind: "terminal" }
  | { id: "git"; kind: "git" }
  | { id: "context"; kind: "context" }
  | {
      id: string;
      kind: "execution";
      surface:
        | "workspace"
        | "git"
        | "jobs"
        | "terminal"
        | "browser"
        | "desktop";
      context: ExecutionContext;
      initialFilePath?: string;
    }
  | { id: string; kind: "file"; path: string; agentId?: string }
  | {
      id: string;
      kind: "knowledge";
      citation: KnowledgeCitation;
    }
  | {
      id: string;
      kind: "toolUi";
      callId: string;
      title?: string;
      toolName?: string;
    };

export type DockTabId = DockTab["id"];

/** Drop retired dock tabs (pre-drawer trajectory) if they appear in stored lists. */
export function ensureNoTrajectoryTab<T extends { kind: string }>(
  tabs: readonly T[],
): T[] {
  return tabs.filter((t) => t.kind !== "trajectory");
}

function loadPanelMode(): PanelMode {
  try {
    const saved = localStorage.getItem(PANEL_MODE_KEY);
    if (saved === "bottom" || saved === "right" || saved === "popup") {
      return saved;
    }
    for (const key of [LEGACY_FILE_MODE_KEY, LEGACY_BROWSER_MODE_KEY]) {
      const legacy = localStorage.getItem(key);
      if (legacy === "bottom" || legacy === "right" || legacy === "popup") {
        return legacy;
      }
    }
  } catch {
    /* ignore */
  }
  return "right";
}

function loadPanelSizes(): PanelSizes {
  try {
    const saved = localStorage.getItem(PANEL_SIZE_KEY);
    if (saved) {
      return JSON.parse(saved) as PanelSizes;
    }
    for (const key of [LEGACY_FILE_SIZE_KEY, LEGACY_BROWSER_SIZE_KEY]) {
      const legacy = localStorage.getItem(key);
      if (legacy) {
        return JSON.parse(legacy) as PanelSizes;
      }
    }
  } catch {
    /* ignore */
  }
  return { rightWidth: 560, bottomHeight: 380 };
}

function persistPanelSizes(sizes: PanelSizes) {
  try {
    localStorage.setItem(PANEL_SIZE_KEY, JSON.stringify(sizes));
  } catch {
    /* ignore */
  }
}

function ensureFilesTab(tabs: DockTab[]): DockTab[] {
  if (tabs.some((t) => t.id === "files")) return tabs;
  return [{ id: "files", kind: "files" }, ...tabs];
}

function fallbackActiveId(
  tabs: DockTab[],
  closedId: DockTabId,
  prevActive: DockTabId | null,
): DockTabId | null {
  if (tabs.length === 0) return null;
  if (prevActive !== closedId && tabs.some((t) => t.id === prevActive)) {
    return prevActive;
  }
  if (tabs.some((t) => t.id === "files")) return "files";
  return tabs[tabs.length - 1]?.id ?? null;
}

/**
 * Shared chat dock with tabbed file list / file viewers / browser / terminal.
 */
export function useChatDockPanel(
  isMobile: boolean,
  agentId?: string | null,
  threadId?: string | null,
  defaultDeviceId?: string,
) {
  const { t } = useTranslation();
  const scope = executionScope(agentId, threadId);
  const currentScope = useRef(scope);
  currentScope.current = scope;
  const [dockOpen, setDockOpen] = useState(false);
  const [dockMode, setDockMode] = useState<PanelMode>(loadPanelMode);
  const [openTabs, setOpenTabs] = useState<DockTab[]>([]);
  const [activeTabId, setActiveTabId] = useState<DockTabId | null>(null);
  const { panelSizes, isResizing, handleResizeStart } = usePanelResize(
    loadPanelSizes(),
    persistPanelSizes,
  );

  // File paths and browser sessions are agent-scoped. Only wipe tabs when
  // switching between two real agents (ignore null ↔ id first-paint races).
  const prevAgentIdRef = useRef(agentId);
  useEffect(() => {
    const prev = prevAgentIdRef.current;
    prevAgentIdRef.current = agentId;
    if (prev == null || agentId == null || prev === agentId) return;
    setDockOpen(false);
    setOpenTabs([]);
    setActiveTabId(null);
  }, [agentId]);

  const openDock = useCallback(() => {
    setDockOpen(true);
    if (isMobile) {
      setDockMode("bottom");
    }
  }, [isMobile]);

  const handleClose = useCallback(() => {
    setDockOpen(false);
    // Closing the dock restores tool UIs to the message stream.
    setOpenTabs((prev) => {
      const next = prev.filter((t) => t.kind !== "toolUi");
      setActiveTabId((current) => {
        if (current == null) return null;
        if (next.some((t) => t.id === current)) return current;
        return next[0]?.id ?? null;
      });
      return next;
    });
  }, []);

  const openFileList = useCallback(() => {
    setOpenTabs((prev) => ensureFilesTab(prev));
    setActiveTabId("files");
    openDock();
  }, [openDock]);

  const openExecutionTab = useCallback(
    async (
      surface:
        | "workspace"
        | "git"
        | "jobs"
        | "terminal"
        | "browser"
        | "desktop",
      initialFilePath?: string,
    ) => {
      const selection = getExecutionSelection(scope);
      if (!agentId) return false;
      if (!executionSelectionReady(scope, threadId)) {
        showApiError(
          new Error(t("devices.sessionSelectionUnavailable")),
          t("devices.sessionSelectionUnavailable"),
          t,
        );
        return true;
      }
      try {
        const context = await executionApi.createContext({
          ...targetFields(selection.deviceId),
          agent_id: agentId,
          thread_id:
            threadId && !threadId.startsWith("__") ? threadId : undefined,
          working_dir: selection.workingDir,
          work_mode: selection.workMode,
        });
        if (currentScope.current !== scope) return true;
        const id = JSON.stringify([
          "execution",
          scope,
          surface,
          context.target_kind,
          context.device_id,
          context.working_dir,
          context.policy_revision,
          context.grant_version,
          context.work_mode,
          initialFilePath ?? "",
        ]);
        setOpenTabs((tabs) =>
          tabs.some((tab) => tab.id === id)
            ? tabs
            : [
                ...tabs,
                { id, kind: "execution", surface, context, initialFilePath },
              ],
        );
        setActiveTabId(id);
        openDock();
      } catch (error) {
        showApiError(error, t("devices.loadFailed"), t);
      }
      return true;
    },
    [scope, agentId, threadId, defaultDeviceId, openDock, t],
  );

  const openFileAt = useCallback(
    (path?: string | null, fileAgentId?: string | null) => {
      if (!path?.trim()) {
        openFileList();
        return;
      }
      if (
        agentId &&
        !path.startsWith("/.agent/") &&
        (!fileAgentId || fileAgentId === agentId)
      ) {
        void openExecutionTab("workspace", path);
        return;
      }
      const ownerId = (fileAgentId || agentId || "").trim() || null;
      const addressedPath = path.startsWith("/.agent/")
        ? path.slice("/.agent".length)
        : path;
      const hostAbs = normalizeDockFilePath(addressedPath);
      // Keep host-absolute tool paths. Collapsing ``~/.octop/agents/<id>/…`` to a
      // relative key breaks virtual ``root_dir`` nests (bytes live under
      // ``{root}/Users/…/.octop/agents/<id>/…``, not the real agent home).
      const tabPath = isHostAbsolutePath(hostAbs)
        ? hostAbs
        : canonicalizeDockFilePath(addressedPath, ownerId);
      if (!tabPath) {
        openFileList();
        return;
      }
      const id = dockFileTabId(tabPath, ownerId);
      setOpenTabs((prev) => {
        if (prev.some((t) => t.id === id)) return prev;
        return [
          ...prev,
          {
            id,
            kind: "file" as const,
            path: tabPath,
            ...(ownerId ? { agentId: ownerId } : {}),
          },
        ];
      });
      setActiveTabId(id);
      openDock();
    },
    [agentId, openDock, openFileList, scope, defaultDeviceId, openExecutionTab],
  );

  const openWorkspaceTab = useCallback(() => {
    void openExecutionTab("workspace");
  }, [openExecutionTab]);

  const openBrowserTab = useCallback(() => {
    void openExecutionTab("browser");
  }, [openExecutionTab]);

  const openTerminalTab = useCallback(() => {
    void openExecutionTab("terminal");
  }, [openExecutionTab]);

  const openGitTab = useCallback(() => {
    void openExecutionTab("git");
  }, [openExecutionTab]);

  const openJobsTab = useCallback(() => {
    void openExecutionTab("jobs");
  }, [openExecutionTab]);

  const openDesktopTab = useCallback(() => {
    void openExecutionTab("desktop");
  }, [openExecutionTab]);

  const openContextTab = useCallback(() => {
    setOpenTabs((prev) =>
      prev.some((t) => t.id === "context")
        ? prev
        : [...prev, { id: "context", kind: "context" }],
    );
    setActiveTabId("context");
    openDock();
  }, [openDock]);

  const openKnowledgeCitation = useCallback(
    (citation: KnowledgeCitation) => {
      const kbId = citation.kbId?.trim();
      const docId = citation.docId?.trim();
      if (!kbId || !docId) return;
      const id = dockKnowledgeTabId(kbId, docId);
      setOpenTabs((prev) => {
        const existing = prev.find((t) => t.id === id);
        if (existing?.kind === "knowledge") {
          return prev.map((t) => (t.id === id ? { ...t, citation } : t));
        }
        if (existing) return prev;
        return [...prev, { id, kind: "knowledge" as const, citation }];
      });
      setActiveTabId(id);
      openDock();
    },
    [openDock],
  );

  const openToolUiTab = useCallback(
    (opts: { callId: string; title?: string; toolName?: string }) => {
      const callId = opts.callId?.trim();
      if (!callId) return;
      const id = dockToolUiTabId(callId);
      setOpenTabs((prev) => {
        if (prev.some((t) => t.id === id)) return prev;
        return [
          ...prev,
          {
            id,
            kind: "toolUi" as const,
            callId,
            title: opts.title,
            toolName: opts.toolName,
          },
        ];
      });
      setActiveTabId(id);
      openDock();
    },
    [openDock],
  );

  const focusToolUiTab = useCallback(
    (callId: string) => {
      const id = dockToolUiTabId(callId);
      setActiveTabId(id);
      openDock();
    },
    [openDock],
  );

  const toggleWorkspacePanel = useCallback(() => {
    void openExecutionTab("workspace");
  }, [openExecutionTab]);

  const toggleBrowserPanel = useCallback(() => {
    void openExecutionTab("browser");
  }, [openExecutionTab]);

  const toggleTerminalPanel = useCallback(() => {
    void openExecutionTab("terminal");
  }, [openExecutionTab]);

  const closeTab = useCallback((id: DockTabId) => {
    setOpenTabs((prev) => {
      const next = prev.filter((t) => t.id !== id);
      setActiveTabId((current) => {
        const nextActive = fallbackActiveId(next, id, current);
        if (next.length === 0) {
          setDockOpen(false);
        }
        return nextActive;
      });
      return next;
    });
  }, []);

  const setActiveTab = useCallback((id: DockTabId) => {
    setActiveTabId(id);
    setDockOpen(true);
  }, []);

  const handleModeChange = useCallback(
    (mode: PanelMode) => {
      if (isMobile && mode === "right") {
        setDockMode("bottom");
        return;
      }
      setDockMode(mode);
    },
    [isMobile],
  );

  useEffect(() => {
    try {
      localStorage.setItem(PANEL_MODE_KEY, dockMode);
    } catch {
      /* ignore */
    }
  }, [dockMode]);

  const activeTab =
    openTabs.find((t) => t.id === activeTabId) ?? openTabs[0] ?? null;
  const filePath = activeTab?.kind === "file" ? activeTab.path : null;

  return {
    dockOpen,
    dockMode,
    filePath,
    openTabs,
    activeTabId,
    activeTab,
    panelSizes,
    isResizing,
    handleResizeStart,
    handleClose,
    handleModeChange,
    openFileAt,
    openFileList,
    openKnowledgeCitation,
    openWorkspaceTab,
    toggleWorkspacePanel,
    openBrowserTab,
    toggleBrowserPanel,
    openTerminalTab,
    openGitTab,
    openJobsTab,
    openDesktopTab,
    openContextTab,
    toggleTerminalPanel,
    openToolUiTab,
    focusToolUiTab,
    closeTab,
    setActiveTab,
  };
}
