import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { chatInputsApi } from "../../../api/modules/chatInputs";
import {
  executionScope,
  setExecutionSelection,
  setExecutionSelectionStatus,
} from "./deviceTarget";
import { usePersistentChatQueue } from "./usePersistentChatQueue";
vi.mock("../../../api/modules/chatInputs", () => ({
  chatInputsApi: {
    list: vi.fn(),
    queue: vi.fn(),
    withdraw: vi.fn(),
    steer: vi.fn(),
  },
}));
vi.mock("./chatStore", () => ({
  hasLiveSocket: () => true,
  attachThread: vi.fn(),
}));
vi.mock("@/utils/antdMessage", () => ({
  message: { error: vi.fn(), info: vi.fn() },
}));
const empty = {
  inputs: [],
  runtime: { run_id: "run", phase: "tool_running" },
  capabilities: { queue: true, steer: true },
};
describe("durable chat input acknowledgement", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(chatInputsApi.list).mockResolvedValue(empty);
    const scope = executionScope("agent", "thread");
    setExecutionSelection(scope, { deviceId: "@local", workMode: "agentic" });
    setExecutionSelectionStatus(scope, "ready");
  });
  const mount = () =>
    renderHook(() =>
      usePersistentChatQueue({ agentId: "agent", threadId: "thread" }),
    );
  it("keeps a stable command and timestamp when an uncertain request is retried", async () => {
    const { result, unmount } = mount();
    await waitFor(() => expect(result.current.runtime?.run_id).toBe("run"));
    vi.mocked(chatInputsApi.queue)
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce({ status: "queued" } as never);
    await act(async () => {
      expect(await result.current.enqueue({ text: "hello" })).toBe("empty");
    });
    await act(async () => {
      expect(await result.current.enqueue({ text: "hello" })).toBe("ok");
    });
    const [first, second] = vi.mocked(chatInputsApi.queue).mock.calls;
    expect(first[2]).toBe(second[2]);
    expect(first[3].createdAt).toBe(second[3].createdAt);
    expect(first[4]).toEqual(second[4]);
    unmount();
  });
  it("treats a confirmed enqueue as success even if receipt refresh fails", async () => {
    const { result, unmount } = mount();
    await waitFor(() => expect(result.current.runtime).not.toBeNull());
    vi.mocked(chatInputsApi.queue).mockResolvedValue({
      status: "queued",
    } as never);
    vi.mocked(chatInputsApi.list).mockRejectedValue(new Error("offline"));
    await act(async () => {
      expect(await result.current.enqueue({ text: "hello" })).toBe("ok");
    });
    unmount();
  });
  it("retains a rejected insertion and targets the current run identity", async () => {
    const { result, unmount } = mount();
    await waitFor(() => expect(result.current.runtime?.run_id).toBe("run"));
    vi.mocked(chatInputsApi.steer).mockResolvedValue({
      status: "stale_run",
    } as never);
    await act(async () => {
      expect(await result.current.steer({ text: "direction" })).toBe(false);
    });
    expect(vi.mocked(chatInputsApi.steer).mock.calls[0].slice(3)).toEqual([
      "run",
      "direction",
    ]);
    unmount();
  });
  it("retires an unknown insertion identity before a later run", async () => {
    const { result, unmount } = mount();
    await waitFor(() => expect(result.current.runtime?.run_id).toBe("run"));
    vi.mocked(chatInputsApi.steer).mockRejectedValueOnce(new Error("offline"));
    await act(async () => {
      expect(await result.current.steer({ text: "direction" })).toBe(false);
    });
    const firstId = vi.mocked(chatInputsApi.steer).mock.calls[0][2];
    vi.mocked(chatInputsApi.steer).mockResolvedValue({
      status: "accepted",
    } as never);
    vi.mocked(chatInputsApi.list).mockResolvedValueOnce({
      inputs: [
        {
          kind: "chat_steer",
          status: "unknown",
          payload: { command_id: firstId, text: "direction" },
        },
      ],
      runtime: null,
      capabilities: { queue: true, steer: true },
    } as never);
    await act(async () => {
      expect(await result.current.steer({ text: "direction" })).toBe(false);
    });
    vi.mocked(chatInputsApi.list).mockResolvedValue(empty);
    await act(async () => {
      expect(await result.current.steer({ text: "direction" })).toBe(true);
    });
    const laterCall = vi.mocked(chatInputsApi.steer).mock.calls[1];
    expect(laterCall[2]).not.toBe(firstId);
    expect(laterCall[3]).toBe("run");
    unmount();
  });
});
