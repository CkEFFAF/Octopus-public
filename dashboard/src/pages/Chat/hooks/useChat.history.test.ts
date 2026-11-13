import { useSessions, resetSessionStoreForTests } from "./useSessions";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { octopThreadsApi } from "../../../api/modules/octopThreads";
import * as chatStore from "./chatStore";
import { useChat, convertHistoryMessages } from "./useChat";

const thread = "versioned-history-test";

afterEach(() => {
  vi.restoreAllMocks();
  chatStore.removeSession(thread);
});

describe("history failures", () => {
  it("reconciles cached history after returning online without dropping loaded older pages", async () => {
    chatStore.setHistoryPage(
      thread,
      [
        { id: "older", role: "user", content: "older", timestamp: 1 },
        { id: "shared", role: "user", content: "old latest", timestamp: 2 },
      ],
      { hasMore: true, nextOffset: 50, nextCursor: "pinned" },
    );
    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    const history = vi.spyOn(octopThreadsApi, "history").mockResolvedValue({
      thread_id: thread,
      messages: [
        { id: "shared", role: "user", content: "old latest" },
        { id: "remote", role: "assistant", content: "finished on workstation" },
      ],
      has_more: true,
    });
    renderHook(() => useChat(thread, "agent"));
    await act(async () => {
      window.dispatchEvent(new Event("online"));
    });
    await waitFor(() => expect(history).toHaveBeenCalled());
    expect(
      chatStore.getSnapshot(thread).messages.map((item) => item.id),
    ).toEqual(["older", "shared", "remote"]);
    expect(chatStore.getSnapshot(thread).historyNextCursor).toBe("pinned");
  });
  it("keeps a loaded conversation and its cursor when refreshing fails", async () => {
    chatStore.setHistoryPage(
      thread,
      [{ id: "old", role: "user", content: "keep me", timestamp: 1 }],
      { hasMore: true, nextOffset: 25, nextCursor: "boundary" },
    );
    vi.spyOn(octopThreadsApi, "history").mockRejectedValue(
      new Error("archive unavailable"),
    );
    const { result } = renderHook(() => useChat(thread, "agent"));
    await act(async () => {
      await result.current.refreshHistory();
    });
    expect(result.current.historyError).toBe(true);
    expect(chatStore.getSnapshot(thread).messages[0].content).toBe("keep me");
    expect(chatStore.getSnapshot(thread).historyNextCursor).toBe("boundary");
    expect(chatStore.getSnapshot(thread).historyHasMore).toBe(true);
  });

  it("does not mark a failed initial load as an empty hydrated conversation", async () => {
    const history = vi
      .spyOn(octopThreadsApi, "history")
      .mockRejectedValueOnce(new Error("decode failed"));
    const { result } = renderHook(() => useChat(thread, "agent"));
    await act(async () => {
      await result.current.loadHistory(thread);
    });
    expect(result.current.historyError).toBe(true);
    expect(chatStore.getSnapshot(thread).historyHydrated).toBe(false);
    history.mockResolvedValueOnce({
      thread_id: thread,
      messages: [{ id: "ok", role: "user", content: "restored" }],
      has_more: false,
    });
    await act(async () => {
      await result.current.loadHistory(thread);
    });
    expect(result.current.historyError).toBe(false);
    expect(chatStore.getSnapshot(thread).historyHydrated).toBe(true);
    expect(chatStore.getSnapshot(thread).messages[0].content).toBe("restored");
  });

  it("refetches a thread cached as empty so background turns show up", async () => {
    chatStore.setHistoryPage(thread, [], {
      hasMore: false,
      nextOffset: 0,
      nextCursor: null,
    });
    const history = vi.spyOn(octopThreadsApi, "history").mockResolvedValue({
      thread_id: thread,
      messages: [{ id: "cron", role: "assistant", content: "task done" }],
      has_more: false,
    });
    const { result } = renderHook(() => useChat(thread, "agent"));
    await act(async () => {
      await result.current.loadHistory(thread);
    });
    expect(history).toHaveBeenCalled();
    expect(chatStore.getSnapshot(thread).messages[0].content).toBe("task done");
  });

  it("passes the pinned cursor when loading older messages", async () => {
    chatStore.setHistoryPage(
      thread,
      [{ id: "new", role: "user", content: "new", timestamp: 1 }],
      { hasMore: true, nextOffset: 25, nextCursor: "pinned-boundary" },
    );
    const history = vi
      .spyOn(octopThreadsApi, "history")
      .mockResolvedValue({ thread_id: thread, messages: [], has_more: false });
    const { result } = renderHook(() => useChat(thread, "agent"));
    await act(async () => {
      await result.current.loadMoreHistory();
    });
    expect(history).toHaveBeenCalledWith(
      "agent",
      thread,
      expect.objectContaining({ cursor: "pinned-boundary" }),
    );
  });
  it("retries the failed older page with the same cursor", async () => {
    chatStore.setHistoryPage(
      thread,
      [{ id: "latest", role: "user", content: "latest", timestamp: 1 }],
      { hasMore: true, nextOffset: 25, nextCursor: "same-boundary" },
    );
    const history = vi
      .spyOn(octopThreadsApi, "history")
      .mockRejectedValueOnce(new Error("unavailable"))
      .mockResolvedValueOnce({
        thread_id: thread,
        messages: [{ id: "older", role: "user", content: "older" }],
        has_more: false,
      });
    const { result } = renderHook(() => useChat(thread, "agent"));
    await act(async () => {
      await result.current.loadMoreHistory();
    });
    expect(result.current.historyError).toBe(true);
    await act(async () => {
      await result.current.retryHistory();
    });
    expect(history).toHaveBeenLastCalledWith(
      "agent",
      thread,
      expect.objectContaining({ cursor: "same-boundary" }),
    );
    expect(result.current.historyError).toBe(false);
    expect(
      chatStore.getSnapshot(thread).messages.map((m) => m.content),
    ).toEqual(["older", "latest"]);
  });
});

it("preserves trusted historical senders for both ACP participants and later human input", () => {
  const messages = convertHistoryMessages([
    {
      id: "prompt",
      role: "user",
      content: "implement",
      sender: { kind: "agent", id: "gpu", name: "GPU专家" },
    },
    {
      id: "reply",
      role: "assistant",
      content: "done",
      sender: { kind: "acp", id: "codex", name: "Codex" },
    },
    { id: "human", role: "user", content: "my reply" },
  ]);
  expect(messages.map((m) => m.sender?.name)).toEqual([
    "GPU专家",
    "Codex",
    undefined,
  ]);
});

it("opens a collaboration deep link in its own category using history metadata", async () => {
  resetSessionStoreForTests();
  vi.spyOn(octopThreadsApi, "list").mockResolvedValue([]);
  vi.spyOn(octopThreadsApi, "history").mockResolvedValue({
    thread_id: thread,
    category: "agent_collaboration",
    actor: { kind: "machine", id: "key", name: "Codex" },
    collaboration_source: { kind: "work_item", device_id: "gpu" },
    messages: [
      {
        id: "input",
        role: "user",
        content: "analyse",
        sender: { kind: "machine", id: "key", name: "Codex" },
      },
    ],
  });
  const { result, unmount } = renderHook(() => ({
    sessions: useSessions("expert", thread),
    chat: useChat(thread, "expert"),
  }));
  await waitFor(() => expect(result.current.sessions.loading).toBe(false));
  await act(async () => {
    await result.current.chat.loadHistory(thread);
  });
  await waitFor(() =>
    expect(result.current.sessions.category).toBe("agent_collaboration"),
  );
  expect(
    result.current.sessions.sessions.find((s) => s.id === thread)
      ?.collaboration_source?.device_id,
  ).toBe("gpu");
  expect(result.current.chat.messages[0].sender?.name).toBe("Codex");
  unmount();
  resetSessionStoreForTests();
});
