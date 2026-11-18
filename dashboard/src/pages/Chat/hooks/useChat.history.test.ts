import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { octopThreadsApi } from "../../../api/modules/octopThreads";
import * as chatStore from "./chatStore";
import { useChat } from "./useChat";

const thread = "versioned-history-test";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  chatStore.removeSession(thread);
});

describe("history failures", () => {
  it("revalidates an unchanged idle page without replacing messages and applies later changes", async () => {
    const page = {
      thread_id: thread,
      messages: [{ id: "one", role: "user", content: "one" }],
      has_more: false,
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (!String(input).includes("/history?"))
        throw new Error("unexpected URL");
      expect(String(input)).toContain("&preview=true");
      const previous = new Headers(init?.headers).get("If-None-Match");
      if (previous === '"first"' && !changed)
        return new Response(null, { status: 304 });
      return Response.json(
        changed
          ? { ...page, messages: [{ ...page.messages[0], content: "updated" }] }
          : page,
        {
          headers: { ETag: changed ? '"second"' : '"first"' },
        },
      );
    });
    const attach = vi
      .spyOn(chatStore, "attachThread")
      .mockResolvedValue(undefined);
    let changed = false;
    vi.stubGlobal("BASE_URL", "");
    const { result } = renderHook(() => useChat(thread, "agent"));
    await act(async () => {
      await result.current.loadHistory(thread);
    });
    const initial = result.current.messages;
    expect(initial[0].content).toBe("one");
    attach.mockClear();
    await act(async () => {
      await result.current.refreshHistory();
    });
    expect(result.current.messages).toBe(initial);
    expect(attach).toHaveBeenCalledOnce();
    changed = true;
    await act(async () => {
      await result.current.refreshHistory();
    });
    expect(result.current.messages[0].content).toBe("updated");
    expect(result.current.messages).not.toBe(initial);
  });

  it("keeps the stored detail location on a restored long response", async () => {
    vi.spyOn(octopThreadsApi, "history").mockResolvedValue({
      thread_id: thread,
      messages: [
        {
          id: "long-answer",
          role: "assistant",
          content: [{ type: "text", text: "A shorter preview…" }],
          detail_cursor: "saved-position",
        },
      ],
    });
    const { result } = renderHook(() => useChat(thread, "agent"));
    await act(async () => {
      await result.current.loadHistory(thread);
    });
    expect(result.current.messages[0]).toMatchObject({
      id: "long-answer",
      content: "A shorter preview…",
      historyDetail: {
        agentId: "agent",
        threadId: thread,
        cursor: "saved-position",
      },
    });
  });

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
