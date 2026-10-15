import { act, renderHook, waitFor } from "@testing-library/react";
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
import { useChatDockPanel } from "./useChatDockPanel";

vi.mock("../../../api/modules/execution", () => ({
  executionApi: { createContext: vi.fn() },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../../../utils/showApiToast", () => ({ showApiError: vi.fn() }));
const context = (device: string): ExecutionContext => ({
  context_id: `context-${device}`,
  device_id: device,
  working_dir: "/work",
  work_mode: "agentic",
  policy_revision: 2,
  grant_version: 3,
});
beforeEach(() => {
  vi.clearAllMocks();
  for (const [agent, thread] of [
    ["local-agent", "local-thread"],
    ["desktop-agent", "desktop-thread"],
    ["browser-agent", "browser-thread"],
    ["dock-agent", "dock-thread"],
    ["default-agent", "thread"],
    ["slow-agent", "first"],
    ["same-expert", "thread-a"],
    ["same-expert", "thread-b"],
  ])
    setExecutionSelectionStatus(executionScope(agent, thread), "ready");
});

describe("device workbench targets", () => {
  it.each(["unknown", "loading", "error"] as const)(
    "blocks new workbench targets while session selection is %s",
    (status) => {
      const scope = executionScope("unready-expert", "unready-thread");
      setExecutionSelectionStatus(scope, status);
      const { result } = renderHook(() =>
        useChatDockPanel(
          false,
          "unready-expert",
          "unready-thread",
          "fallback-device",
        ),
      );
      act(() => {
        result.current.openBrowserTab();
        result.current.openTerminalTab();
        result.current.openGitTab();
      });
      expect(executionApi.createContext).not.toHaveBeenCalled();
      expect(result.current.openTabs).toHaveLength(0);
    },
  );
  it("uses a typed explicit local target and freezes it in the tab", async () => {
    setExecutionSelection(executionScope("local-agent", "local-thread"), {
      deviceId: "@local",
    });
    vi.mocked(executionApi.createContext).mockResolvedValue({
      ...context(""),
      device_id: null,
      target_kind: "local",
    });
    const { result } = renderHook(() =>
      useChatDockPanel(false, "local-agent", "local-thread"),
    );
    act(() => result.current.openTerminalTab());
    await waitFor(() => expect(result.current.openTabs).toHaveLength(1));
    expect(executionApi.createContext).toHaveBeenCalledWith(
      expect.objectContaining({ target_kind: "local" }),
    );
    expect(
      vi.mocked(executionApi.createContext).mock.calls[0][0].device_id,
    ).toBeUndefined();
    setExecutionSelection(executionScope("local-agent", "local-thread"), {
      deviceId: "gpu",
    });
    expect(result.current.openTabs[0]).toMatchObject({
      kind: "execution",
      context: { target_kind: "local", device_id: null },
    });
  });
  it("opens desktop control with the same frozen target as other surfaces", async () => {
    setExecutionSelection(executionScope("desktop-agent", "desktop-thread"), {
      deviceId: "laptop",
      workMode: "computer_use",
    });
    vi.mocked(executionApi.createContext).mockResolvedValue({
      ...context("laptop"),
      work_mode: "computer_use",
    });
    const { result } = renderHook(() =>
      useChatDockPanel(false, "desktop-agent", "desktop-thread"),
    );
    act(() => result.current.openDesktopTab());
    await waitFor(() => expect(result.current.openTabs).toHaveLength(1));
    expect(result.current.openTabs[0]).toMatchObject({
      kind: "execution",
      surface: "desktop",
      context: { device_id: "laptop", work_mode: "computer_use" },
    });
  });
  it("routes browser preview through the selected device context", async () => {
    const scope = executionScope("browser-agent", "browser-thread");
    setExecutionSelection(scope, { deviceId: "gpu" });
    vi.mocked(executionApi.createContext).mockResolvedValue(context("gpu"));
    const { result } = renderHook(() =>
      useChatDockPanel(false, "browser-agent", "browser-thread"),
    );
    act(() => result.current.openBrowserTab());
    await waitFor(() => expect(result.current.openTabs).toHaveLength(1));
    expect(result.current.openTabs[0]).toMatchObject({
      kind: "execution",
      surface: "browser",
      context: { device_id: "gpu" },
    });
  });
  it("keeps an open tab on its original target after selecting another device", async () => {
    const scope = executionScope("dock-agent", "dock-thread");
    setExecutionSelection(scope, { deviceId: "gpu", workingDir: "/work" });
    vi.mocked(executionApi.createContext)
      .mockResolvedValueOnce(context("gpu"))
      .mockResolvedValueOnce(context("laptop"));
    const { result } = renderHook(() =>
      useChatDockPanel(false, "dock-agent", "dock-thread"),
    );
    act(() => result.current.openGitTab());
    await waitFor(() => expect(result.current.openTabs).toHaveLength(1));
    setExecutionSelection(scope, { deviceId: "laptop" });
    act(() => result.current.openGitTab());
    await waitFor(() => expect(result.current.openTabs).toHaveLength(2));
    const tabs = result.current.openTabs.filter(
      (tab) => tab.kind === "execution",
    );
    expect(tabs.map((tab) => tab.context.device_id)).toEqual(["gpu", "laptop"]);
    expect(tabs[0].context.context_id).toBe("context-gpu");
    expect(executionApi.createContext).toHaveBeenLastCalledWith(
      expect.objectContaining({
        device_id: "laptop",
        thread_id: "dock-thread",
      }),
    );
  });

  it("uses the expert default and retains the native file path", async () => {
    vi.mocked(executionApi.createContext).mockResolvedValue(context("gpu"));
    const { result } = renderHook(() =>
      useChatDockPanel(false, "default-agent", "thread", "gpu"),
    );
    act(() => result.current.openFileAt("/home/user/experiment/log.txt"));
    await waitFor(() => expect(result.current.openTabs).toHaveLength(1));
    const tab = result.current.openTabs[0];
    expect(tab.kind).toBe("execution");
    if (tab.kind === "execution")
      expect(tab.initialFilePath).toBe("/home/user/experiment/log.txt");
  });

  it("does not insert a late context into a different chat", async () => {
    let resolve!: (value: ExecutionContext) => void;
    vi.mocked(executionApi.createContext).mockReturnValue(
      new Promise((value) => {
        resolve = value;
      }),
    );
    const { result, rerender } = renderHook(
      ({ thread }) => useChatDockPanel(false, "slow-agent", thread, "gpu"),
      { initialProps: { thread: "first" } },
    );
    act(() => result.current.openWorkspaceTab());
    rerender({ thread: "second" });
    await act(async () => resolve(context("gpu")));
    expect(result.current.openTabs).toHaveLength(0);
  });

  it.each(["browser", "desktop", "terminal"] as const)(
    "opens a separate %s context after a same expert thread switch",
    async (surface) => {
      vi.mocked(executionApi.createContext)
        .mockResolvedValueOnce({
          ...context("gpu"),
          context_id: "thread-a-context",
        })
        .mockResolvedValueOnce({
          ...context("gpu"),
          context_id: "thread-b-context",
        })
        .mockResolvedValueOnce({
          ...context("gpu"),
          context_id: "thread-b-reopened",
        });
      const { result, rerender } = renderHook(
        ({ thread }) => useChatDockPanel(false, "same-expert", thread),
        { initialProps: { thread: "thread-a" } },
      );
      const open = () => {
        if (surface === "browser") result.current.openBrowserTab();
        else if (surface === "desktop") result.current.openDesktopTab();
        else result.current.openTerminalTab();
      };
      act(open);
      await waitFor(() => expect(result.current.openTabs).toHaveLength(1));
      const firstId = result.current.activeTabId;
      rerender({ thread: "thread-b" });
      act(open);
      await waitFor(() => expect(result.current.openTabs).toHaveLength(2));
      expect(result.current.activeTabId).not.toBe(firstId);
      expect(result.current.openTabs[0]).toMatchObject({
        context: { context_id: "thread-a-context" },
      });
      expect(result.current.activeTab).toMatchObject({
        context: { context_id: "thread-b-context" },
      });
      expect(executionApi.createContext).toHaveBeenLastCalledWith(
        expect.objectContaining({
          agent_id: "same-expert",
          thread_id: "thread-b",
        }),
      );
      act(open);
      await waitFor(() =>
        expect(executionApi.createContext).toHaveBeenCalledTimes(3),
      );
      expect(result.current.openTabs).toHaveLength(2);
      expect(result.current.activeTab).toMatchObject({
        context: { context_id: "thread-b-context" },
      });
    },
  );
});
