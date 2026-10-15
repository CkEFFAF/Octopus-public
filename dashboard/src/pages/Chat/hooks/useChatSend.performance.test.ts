import { act, renderHook } from "@testing-library/react";
import type { TFunction } from "i18next";
import { describe, expect, it, vi } from "vitest";
import { useChatSend } from "./useChatSend";
import {
  executionScope,
  setExecutionSelection,
  setExecutionSelectionStatus,
} from "./deviceTarget";

const navigation = vi.hoisted(() => vi.fn());
vi.mock("react-router-dom", () => ({ useNavigate: () => navigation }));
vi.mock("@/utils/antdMessage", () => ({
  message: { warning: vi.fn(), info: vi.fn(), error: vi.fn() },
}));

describe("composer actions during streaming", () => {
  it("keeps the send action stable for unchanged selection and uses updated selection", () => {
    const options = {
      resolvedAgentId: "perf-expert",
      activeThreadId: "perf-thread",
      sessions: [],
      messagesLength: 2,
      selectedModel: null,
      selectedConnectors: [],
      selectedKnowledgeBaseIds: [],
      reasoningMode: "auto" as const,
      reasoningEffort: null,
      sendMessage: vi.fn(),
      createSession: vi.fn(),
      renameSession: vi.fn(),
      t: ((key: string) => key) as TFunction,
    };
    const scope = executionScope(
      options.resolvedAgentId,
      options.activeThreadId,
    );
    setExecutionSelection(scope, {
      deviceId: "gpu",
      workingDir: "/workspace",
      workMode: "agentic",
    });
    setExecutionSelectionStatus(scope, "ready");
    const { result, rerender } = renderHook((props) => useChatSend(props), {
      initialProps: options,
    });
    const first = result.current.handleSend;
    for (let i = 0; i < 20; i++) rerender(options);
    expect(result.current.handleSend).toBe(first);
    act(() =>
      setExecutionSelection(scope, {
        deviceId: "laptop",
        workingDir: "D:/project",
      }),
    );
    act(() => expect(result.current.handleSend("inspect")).toBe(true));
    expect(options.sendMessage.mock.calls[0].slice(-3)).toEqual([
      "laptop",
      "agentic",
      "D:/project",
    ]);
  });
});
