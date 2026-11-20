import { beforeEach, describe, expect, it, vi } from "vitest";
import { octopThreadsApi } from "../../../api/modules/octopThreads";
import type { ChatMessage } from "../hooks/useChat";
import { prependMessageQuote, resolveMessageQuote } from "./messageQuote";

vi.mock("../../../api/modules/octopThreads", () => ({
  octopThreadsApi: { history: vi.fn() },
}));

const reply: ChatMessage = {
  id: "answer",
  role: "assistant",
  content: "preview",
  status: "done",
  timestamp: 0,
  historyDetail: { agentId: "agent", threadId: "thread", cursor: "detail" },
};

beforeEach(() => vi.resetAllMocks());

describe("message quotes", () => {
  it("quotes every line, including nested quotes, while keeping the question intact", () => {
    expect(
      prependMessageQuote("Why?", "first\r\n\r\n> nested\n/skill", "Reply"),
    ).toBe("> Reply\n> first\n> \n> > nested\n> /skill\n\nWhy?");
    expect(prependMessageQuote("keep", "  ", "Reply")).toBe("keep");
  });

  it("keeps normal messages without fetching history", async () => {
    expect(
      await resolveMessageQuote({ ...reply, historyDetail: undefined }),
    ).toBe("preview");
    expect(octopThreadsApi.history).not.toHaveBeenCalled();
  });

  it("loads complete history and retains earlier answer fragments", async () => {
    vi.mocked(octopThreadsApi.history).mockResolvedValue({
      thread_id: "thread",
      detail_cursor: "detail",
      messages: [{ role: "assistant", content: "complete final fragment" }],
    });
    const first = {
      ...reply,
      id: "first",
      content: "first fragment",
      historyDetail: undefined,
    };
    expect(await resolveMessageQuote(reply, [first, reply])).toBe(
      "first fragment complete final fragment",
    );
    expect(octopThreadsApi.history).toHaveBeenCalledWith("agent", "thread", {
      limit: 1,
      cursor: "detail",
    });
  });

  it.each([
    { thread_id: "other" },
    { detail_cursor: "other" },
    { history_loading: true },
    { messages: [{ role: "user", content: "wrong message" }] },
    { messages: [] },
  ])("rejects unvalidated history detail %j", async (change) => {
    vi.mocked(octopThreadsApi.history).mockResolvedValue({
      thread_id: "thread",
      detail_cursor: "detail",
      messages: [{ role: "assistant", content: "full" }],
      ...change,
    });
    await expect(resolveMessageQuote(reply)).rejects.toThrow();
  });
});
