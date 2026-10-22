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
    promote: vi.fn(),
    dismiss: vi.fn(),
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
  it("dismisses only a terminal receipt and refreshes without resending", async () => {
    const { result, unmount } = mount();
    await waitFor(() => expect(result.current.runtime?.run_id).toBe("run"));
    vi.mocked(chatInputsApi.dismiss).mockResolvedValue({
      status: "dismissed",
    } as never);
    await act(async () => {
      expect(await result.current.dismiss("old-status")).toBe(true);
    });
    expect(chatInputsApi.dismiss).toHaveBeenCalledExactlyOnceWith(
      "agent",
      "thread",
      "old-status",
    );
    expect(chatInputsApi.queue).not.toHaveBeenCalled();
    expect(chatInputsApi.promote).not.toHaveBeenCalled();
    unmount();
  });
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
  it("promotes the existing queue identity without withdrawing or resubmitting its text", async () => {
    const { result, unmount } = mount();
    await waitFor(() => expect(result.current.runtime?.run_id).toBe("run"));
    vi.mocked(chatInputsApi.promote).mockResolvedValue({
      status: "accepted",
    } as never);
    await act(async () => {
      expect(await result.current.promote("queued-id")).toBe(true);
    });
    expect(chatInputsApi.promote).toHaveBeenCalledExactlyOnceWith(
      "agent",
      "thread",
      "queued-id",
      "run",
      false,
    );
    expect(chatInputsApi.withdraw).not.toHaveBeenCalled();
    expect(chatInputsApi.steer).not.toHaveBeenCalled();
    unmount();
  });

  it("forwards immediate mode and shows acknowledged interruption state", async () => {
    const { result, unmount } = mount();
    await waitFor(() => expect(result.current.runtime?.run_id).toBe("run"));
    vi.mocked(chatInputsApi.promote).mockImplementation(async () => {
      vi.mocked(chatInputsApi.list).mockResolvedValue({
        ...empty,
        inputs: [
          {
            kind: "chat_steer",
            status: "accepted",
            payload: {
              command_id: "queued-id",
              text: "now",
              cancel_tools: true,
            },
          },
        ],
      } as never);
      return { status: "accepted" } as never;
    });
    await act(async () => {
      expect(await result.current.promote("queued-id", true)).toBe(true);
    });
    expect(chatInputsApi.promote).toHaveBeenCalledExactlyOnceWith(
      "agent",
      "thread",
      "queued-id",
      "run",
      true,
    );
    expect(result.current.items[0].status).toBe("interrupting");
    unmount();
  });

  it("refreshes queue receipts after a failed promotion without deleting the item", async () => {
    const { result, unmount } = mount();
    await waitFor(() => expect(result.current.runtime?.run_id).toBe("run"));
    vi.mocked(chatInputsApi.promote).mockRejectedValue(new Error("busy"));
    vi.mocked(chatInputsApi.list).mockResolvedValue({
      ...empty,
      inputs: [
        {
          kind: "chat_input",
          status: "queued",
          payload: { command_id: "queued-id", snapshot: { text: "keep me" } },
        },
      ],
    } as never);
    await act(async () => {
      expect(await result.current.promote("queued-id")).toBe(false);
    });
    expect(result.current.items[0]).toMatchObject({
      id: "queued-id",
      text: "keep me",
      status: "queued",
    });
    expect(chatInputsApi.withdraw).not.toHaveBeenCalled();
    unmount();
  });

  it("recognizes a previously accepted promotion after a lost response even in a later run", async () => {
    const { result, unmount } = mount();
    await waitFor(() => expect(result.current.runtime?.run_id).toBe("run"));
    vi.mocked(chatInputsApi.list).mockResolvedValue({
      ...empty,
      runtime: { run_id: "next-run", phase: "llm_running" },
      inputs: [
        {
          kind: "chat_steer",
          status: "applied",
          payload: { command_id: "queued-id" },
        },
      ],
    } as never);
    await act(async () => {
      expect(await result.current.promote("queued-id")).toBe(true);
    });
    expect(chatInputsApi.promote).not.toHaveBeenCalled();
    unmount();
  });
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
