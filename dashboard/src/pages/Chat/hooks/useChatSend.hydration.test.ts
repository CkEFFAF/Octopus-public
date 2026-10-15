import { act, renderHook } from "@testing-library/react";
import type { TFunction } from "i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { message } from "@/utils/antdMessage";
import {
  executionScope,
  setExecutionSelection,
  setExecutionSelectionStatus,
} from "./deviceTarget";
import { useChatSend } from "./useChatSend";

vi.mock("react-router-dom", () => ({ useNavigate: () => vi.fn() }));
vi.mock("@/utils/antdMessage", () => ({
  message: { warning: vi.fn(), info: vi.fn(), error: vi.fn() },
}));

beforeEach(() => vi.clearAllMocks());

const props = () => ({
  resolvedAgentId: "send-expert",
  activeThreadId: "send-thread",
  sessions: [],
  messagesLength: 1,
  selectedModel: null,
  selectedConnectors: [],
  selectedKnowledgeBaseIds: [],
  reasoningMode: "auto" as const,
  reasoningEffort: null,
  sendMessage: vi.fn(),
  createSession: vi.fn(),
  renameSession: vi.fn(),
  t: ((key: string) => key) as TFunction,
});

describe("chat execution selection hydration", () => {
  it.each(["unknown", "loading", "error"] as const)(
    "blocks sending with a %s persisted target",
    (status) => {
      const options = props();
      setExecutionSelectionStatus(
        executionScope("send-expert", "send-thread"),
        status,
      );
      const { result } = renderHook(() => useChatSend(options));
      act(() =>
        expect(result.current.handleSend("inspect the project")).toBe(false),
      );
      expect(options.sendMessage).not.toHaveBeenCalled();
      expect(message.warning).toHaveBeenCalledWith(
        "devices.sessionSelectionUnavailable",
      );
    },
  );

  it("sends with the successfully restored device and native directory", () => {
    const options = props();
    const scope = executionScope("send-expert", "send-thread");
    setExecutionSelection(scope, {
      deviceId: "saved-gpu",
      workingDir: "/srv/experiment",
      workMode: "debug",
    });
    setExecutionSelectionStatus(scope, "ready");
    const { result } = renderHook(() => useChatSend(options));
    act(() =>
      expect(result.current.handleSend("inspect the project")).toBe(true),
    );
    expect(options.sendMessage).toHaveBeenCalledTimes(1);
    expect(options.sendMessage.mock.calls[0].slice(-3)).toEqual([
      "saved-gpu",
      "debug",
      "/srv/experiment",
    ]);
  });

  it("flushes a background scoped snapshot without inheriting the active thread's mode or directory", () => {
    const options = {
      ...props(),
      activeThreadId: "another-thread",
      conversationMode: "plan" as const,
    };
    const scope = executionScope("send-expert", "send-thread");
    setExecutionSelection(scope, {
      deviceId: "ambient-device",
      workingDir: "/ambient",
      workMode: "plan",
    });
    setExecutionSelectionStatus(scope, "unknown");
    const { result } = renderHook(() => useChatSend(options));
    act(() =>
      expect(
        result.current.handleSend("queued work", undefined, {
          agentId: "send-expert",
          threadId: "send-thread",
          executionSelection: {
            scope,
            deviceId: "frozen-gpu",
            workMode: "debug",
          },
        }),
      ).toBe(true),
    );
    expect(options.sendMessage.mock.calls[0].slice(-3)).toEqual([
      "frozen-gpu",
      "debug",
      undefined,
    ]);
    expect(options.sendMessage.mock.calls[0][12]).toBe("craft");
  });

  it("does not treat a snapshot from another thread as restored target authority", () => {
    const options = props();
    const scope = executionScope("send-expert", "send-thread");
    setExecutionSelectionStatus(scope, "error");
    const { result } = renderHook(() => useChatSend(options));
    act(() =>
      expect(
        result.current.handleSend("queued work", undefined, {
          executionSelection: {
            scope: executionScope("send-expert", "wrong-thread"),
            deviceId: "frozen-gpu",
            workMode: "debug",
          },
        }),
      ).toBe(false),
    );
    expect(options.sendMessage).not.toHaveBeenCalled();
  });
});
