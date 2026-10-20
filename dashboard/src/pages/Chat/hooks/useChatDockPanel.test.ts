import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  executionApi,
  type ExecutionContext,
} from "../../../api/modules/execution";
import {
  executionScope,
  setExecutionSelection,
  setExecutionSelectionStatus,
} from "./deviceTarget";
import { dockFileTabId } from "../utils/dockFilePath";
import { dockKnowledgeTabId } from "../utils/dockKnowledgeTabId";
import { ensureNoTrajectoryTab, useChatDockPanel } from "./useChatDockPanel";

vi.mock("../../../api/modules/execution", () => ({
  executionApi: { createContext: vi.fn() },
}));
const context: ExecutionContext = {
  context_id: "authorized-context",
  device_id: "fixture-device",
  target_kind: "device",
  working_dir: "/samples",
  work_mode: "agentic",
  policy_revision: 1,
  grant_version: 1,
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(executionApi.createContext).mockResolvedValue(context);
  setExecutionSelection(executionScope("main", "thread"), {
    deviceId: "fixture-device",
    workingDir: "/samples",
    workMode: "agentic",
  });
  setExecutionSelectionStatus(executionScope("main", "thread"), "ready");
});
function renderExecutionDock() {
  return renderHook(() => useChatDockPanel(false, "main", "thread"));
}

describe("useChatDockPanel tabs", () => {
  it("does not open execution surfaces without an agent identity", async () => {
    const { result } = renderHook(() => useChatDockPanel(false));
    await act(async () => {
      result.current.openBrowserTab();
      result.current.openTerminalTab();
    });
    expect(executionApi.createContext).not.toHaveBeenCalled();
    expect(result.current.openTabs).toEqual([]);
    expect(result.current.dockOpen).toBe(false);
  });

  it("does not attach a late authorized context after switching agent scope", async () => {
    let finish!: (value: ExecutionContext) => void;
    vi.mocked(executionApi.createContext).mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const { result, rerender } = renderHook(
      ({ agentId }) => useChatDockPanel(false, agentId, "thread"),
      { initialProps: { agentId: "main" } },
    );
    act(() => result.current.openTerminalTab());
    rerender({ agentId: "other" });
    await act(async () => finish(context));
    expect(result.current.openTabs).toEqual([]);
    expect(result.current.dockOpen).toBe(false);
  });

  it("openFileList focuses the pinned files tab", () => {
    const { result } = renderHook(() => useChatDockPanel(false));
    act(() => {
      result.current.openFileList();
    });
    expect(result.current.dockOpen).toBe(true);
    expect(result.current.activeTabId).toBe("files");
    expect(result.current.openTabs.map((t) => t.id)).toEqual(["files"]);
  });

  it("openFileAt dedupes normalized explicit-agent paths without creating a device context", () => {
    const { result } = renderHook(() => useChatDockPanel(false, "main"));
    act(() => result.current.openFileAt("/.agent/outbound/a.txt"));
    act(() => result.current.openFileAt(String.raw`/.agent/outbound\a.txt`));
    expect(
      result.current.openTabs.filter((t) => t.kind === "file"),
    ).toHaveLength(1);
    expect(result.current.activeTabId).toBe(
      dockFileTabId("/outbound/a.txt", "main"),
    );
    expect(executionApi.createContext).not.toHaveBeenCalled();
  });

  it("openKnowledgeCitation opens a dock tab and dedupes by kb/doc id", () => {
    const { result } = renderHook(() => useChatDockPanel(false));
    const citation = {
      kbId: "kb1",
      docId: "doc1",
      kbName: "Personal",
      filename: "a.md",
    };
    act(() => {
      result.current.openKnowledgeCitation(citation);
    });
    expect(result.current.dockOpen).toBe(true);
    expect(result.current.activeTabId).toBe(dockKnowledgeTabId("kb1", "doc1"));
    act(() => {
      result.current.openKnowledgeCitation({
        ...citation,
        filename: "renamed.md",
      });
    });
    const knowledgeTabs = result.current.openTabs.filter(
      (t) => t.kind === "knowledge",
    );
    expect(knowledgeTabs).toHaveLength(1);
    expect(knowledgeTabs[0]).toMatchObject({
      kind: "knowledge",
      citation: { filename: "renamed.md" },
    });
  });

  it("focuses the authorized workspace and reuses its tab on repeated opens", async () => {
    const { result } = renderExecutionDock();
    await act(async () => {
      result.current.toggleWorkspacePanel();
    });
    expect(executionApi.createContext).toHaveBeenCalledWith({
      device_id: "fixture-device",
      agent_id: "main",
      thread_id: "thread",
      working_dir: "/samples",
      work_mode: "agentic",
    });
    expect(result.current.activeTab).toMatchObject({
      kind: "execution",
      surface: "workspace",
      context,
    });
    expect(result.current.dockOpen).toBe(true);
    await act(async () => {
      result.current.toggleWorkspacePanel();
    });
    expect(result.current.openTabs).toHaveLength(1);
    expect(result.current.dockOpen).toBe(true);
    act(() => result.current.handleClose());
    expect(result.current.dockOpen).toBe(false);
    expect(result.current.openTabs).toHaveLength(1);
  });

  it("focuses the authorized browser and reuses its tab on repeated opens", async () => {
    const { result } = renderExecutionDock();
    await act(async () => {
      result.current.toggleBrowserPanel();
    });
    expect(executionApi.createContext).toHaveBeenCalledWith({
      device_id: "fixture-device",
      agent_id: "main",
      thread_id: "thread",
      working_dir: "/samples",
      work_mode: "agentic",
    });
    expect(result.current.activeTab).toMatchObject({
      kind: "execution",
      surface: "browser",
      context,
    });
    expect(result.current.dockOpen).toBe(true);
    await act(async () => {
      result.current.toggleBrowserPanel();
    });
    expect(result.current.openTabs).toHaveLength(1);
    expect(result.current.dockOpen).toBe(true);
    act(() => result.current.handleClose());
    expect(result.current.dockOpen).toBe(false);
    expect(result.current.openTabs).toHaveLength(1);
  });

  it("focuses the authorized terminal and reuses its tab on repeated opens", async () => {
    const { result } = renderExecutionDock();
    await act(async () => {
      result.current.toggleTerminalPanel();
    });
    expect(executionApi.createContext).toHaveBeenCalledWith({
      device_id: "fixture-device",
      agent_id: "main",
      thread_id: "thread",
      working_dir: "/samples",
      work_mode: "agentic",
    });
    expect(result.current.activeTab).toMatchObject({
      kind: "execution",
      surface: "terminal",
      context,
    });
    expect(result.current.dockOpen).toBe(true);
    await act(async () => {
      result.current.toggleTerminalPanel();
    });
    expect(result.current.openTabs).toHaveLength(1);
    expect(result.current.dockOpen).toBe(true);
    act(() => result.current.handleClose());
    expect(result.current.dockOpen).toBe(false);
    expect(result.current.openTabs).toHaveLength(1);
  });

  it("ensureNoTrajectoryTab strips leftover trajectory tabs", () => {
    expect(
      ensureNoTrajectoryTab([
        { id: "files", kind: "files" },
        { id: "trajectory", kind: "trajectory" },
        { id: "browser", kind: "browser" },
      ]),
    ).toEqual([
      { id: "files", kind: "files" },
      { id: "browser", kind: "browser" },
    ]);
  });

  it("reopening terminal does not add another authorized dock tab", async () => {
    const { result } = renderExecutionDock();
    await act(async () => {
      result.current.openTerminalTab();
    });
    act(() => result.current.handleClose());
    await act(async () => {
      result.current.openTerminalTab();
    });
    expect(result.current.dockOpen).toBe(true);
    expect(result.current.openTabs).toHaveLength(1);
    expect(result.current.activeTab).toMatchObject({
      kind: "execution",
      surface: "terminal",
      context,
    });
  });

  it("openTerminalTab focuses its authorized tab while retaining the browser", async () => {
    const { result } = renderExecutionDock();
    await act(async () => {
      result.current.openBrowserTab();
    });
    await act(async () => {
      result.current.openTerminalTab();
    });
    expect(result.current.activeTab).toMatchObject({
      kind: "execution",
      surface: "terminal",
    });
    expect(
      result.current.openTabs.map((t) =>
        t.kind === "execution" ? t.surface : t.kind,
      ),
    ).toEqual(["browser", "terminal"]);
  });

  it("closeTab closes the files list while keeping the authorized browser selected", async () => {
    const { result } = renderExecutionDock();
    act(() => result.current.openFileList());
    await act(async () => {
      result.current.openBrowserTab();
    });
    act(() => result.current.closeTab("files"));
    expect(result.current.openTabs).toHaveLength(1);
    expect(result.current.activeTab).toMatchObject({
      kind: "execution",
      surface: "browser",
    });
    expect(result.current.dockOpen).toBe(true);
  });

  it("closing the last authorized tab closes the dock", async () => {
    const { result } = renderExecutionDock();
    await act(async () => {
      result.current.openBrowserTab();
    });
    const id = result.current.activeTabId;
    expect(id).toBeTruthy();
    act(() => result.current.closeTab(id!));
    expect(result.current.openTabs).toEqual([]);
    expect(result.current.dockOpen).toBe(false);
  });

  it("openToolUiTab dedupes by callId and focuses the tool tab", () => {
    const { result } = renderHook(() => useChatDockPanel(false));
    act(() => {
      result.current.openToolUiTab({
        callId: "call-1",
        title: "Demo card",
        toolName: "demo_card",
      });
    });
    act(() => {
      result.current.openToolUiTab({
        callId: "call-1",
        title: "Demo card",
      });
    });
    expect(result.current.dockOpen).toBe(true);
    expect(
      result.current.openTabs.filter((t) => t.kind === "toolUi"),
    ).toHaveLength(1);
    expect(result.current.activeTabId).toBe("toolUi:call-1");
    expect(result.current.openTabs[0]).toMatchObject({
      kind: "toolUi",
      callId: "call-1",
      title: "Demo card",
    });
  });

  it("focusToolUiTab reopens dock on an existing tool tab", () => {
    const { result } = renderHook(() => useChatDockPanel(false));
    act(() => {
      result.current.openToolUiTab({ callId: "call-2", title: "Card" });
      result.current.handleClose();
    });
    expect(result.current.dockOpen).toBe(false);
    // Closing the dock drops toolUi tabs so the message stream restores.
    expect(
      result.current.openTabs.filter((t) => t.kind === "toolUi"),
    ).toHaveLength(0);
    act(() => {
      result.current.openToolUiTab({ callId: "call-2", title: "Card" });
    });
    expect(result.current.dockOpen).toBe(true);
    expect(result.current.activeTabId).toBe("toolUi:call-2");
  });

  it("handleClose removes toolUi tabs but retains the authorized browser", async () => {
    const { result } = renderExecutionDock();
    await act(async () => {
      result.current.openBrowserTab();
    });
    act(() =>
      result.current.openToolUiTab({ callId: "call-3", title: "Card" }),
    );
    act(() => result.current.handleClose());
    expect(result.current.dockOpen).toBe(false);
    expect(result.current.openTabs).toHaveLength(1);
    expect(result.current.activeTab).toMatchObject({
      kind: "execution",
      surface: "browser",
    });
  });

  it("does not expose deprecated dismiss / kind aliases", () => {
    const { result } = renderHook(() => useChatDockPanel(false));
    expect(result.current).not.toHaveProperty("userDismissedRef");
    expect(result.current).not.toHaveProperty("dockKind");
    expect(result.current).not.toHaveProperty("openFilePanel");
    expect(result.current).not.toHaveProperty("openBrowserPanel");
    expect(result.current).not.toHaveProperty("resetDismissOnSessionGone");
    expect(result.current).not.toHaveProperty("toggleTrajectoryPanel");
  });

  it("closes the dock and clears tabs when agentId changes", () => {
    const { result, rerender } = renderHook(
      ({ agentId }: { agentId: string | null }) =>
        useChatDockPanel(false, agentId),
      { initialProps: { agentId: "agent-a" as string | null } },
    );
    act(() => {
      result.current.openFileList();
      result.current.openBrowserTab();
    });
    expect(result.current.dockOpen).toBe(true);
    expect(result.current.openTabs.length).toBeGreaterThan(0);

    rerender({ agentId: "agent-b" });

    expect(result.current.dockOpen).toBe(false);
    expect(result.current.openTabs).toEqual([]);
    expect(result.current.activeTabId).toBeNull();
  });

  it("does not clear dock on null ↔ id first paint races", () => {
    const { result, rerender } = renderHook(
      ({ agentId }: { agentId: string | null }) =>
        useChatDockPanel(false, agentId),
      { initialProps: { agentId: null as string | null } },
    );
    rerender({ agentId: "agent-a" });
    act(() => {
      result.current.openFileList();
    });
    expect(result.current.dockOpen).toBe(true);
    // Same agent again after transient identity — keep open.
    rerender({ agentId: "agent-a" });
    expect(result.current.dockOpen).toBe(true);
  });
});
