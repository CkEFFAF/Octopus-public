import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cancelStream,
  getSnapshot,
  ingestHarnessChunk,
  removeSession,
  sendTurn,
  setFocusedChatSession,
  setHistoryPage,
  subscribe,
} from "./chatStore";

vi.mock("../../../api/modules/wsChat", () => ({
  buildDashboardChatWsUrl: () => "ws://localhost/batching-test",
}));

const SESSION = "batching-thread";
const OTHER = "batching-other";

/** Replay the same JSON frame entry point used by the dashboard socket. */
class Socket {
  static OPEN = 1;
  static instances: Socket[] = [];
  readyState = 1;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() {
    Socket.instances.push(this);
  }
  send() {}
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  frame(frame: Record<string, unknown>) {
    this.onmessage?.({
      data: JSON.stringify({ thread_id: SESSION, ...frame }),
    });
  }
}

beforeEach(() => {
  vi.useFakeTimers({
    toFake: [
      "setTimeout",
      "clearTimeout",
      "setInterval",
      "clearInterval",
      "Date",
    ],
  });
  vi.stubGlobal("WebSocket", Socket);
});

afterEach(() => {
  removeSession(SESSION);
  removeSession(OTHER);
  setFocusedChatSession(null);
  Socket.instances = [];
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("chat stream notification batching", () => {
  it("coalesces a 300-frame WS burst while preserving every text fragment", async () => {
    const turn = sendTurn(SESSION, "start", "host", "session-key");
    const socket = Socket.instances[0];
    socket.onopen?.();
    const listener = vi.fn();
    const unsubscribe = subscribe(SESSION, listener);
    const initial = getSnapshot(SESSION);
    const fragments = Array.from({ length: 300 }, (_, i) => `[${i}]`);
    for (const content of fragments) socket.frame({ type: "token", content });

    expect(getSnapshot(SESSION).messages[0].content).toBe(fragments.join(""));
    expect(initial.messages).toEqual([]);
    expect(getSnapshot(SESSION)).toBe(getSnapshot(SESSION));
    expect(listener.mock.calls.length).toBeLessThanOrEqual(1);
    vi.advanceTimersByTime(32);
    expect(listener).toHaveBeenCalledTimes(1);
    socket.frame({ type: "done" });
    await turn;
    const complete = getSnapshot(SESSION);
    expect(complete.messages[0].content).toBe(fragments.join(""));
    expect(complete.messages[0].status).toBe("done");
    expect(complete.isStreaming).toBe(false);
    const callsAtDone = listener.mock.calls.length;
    vi.advanceTimersByTime(64);
    expect(listener).toHaveBeenCalledTimes(callsAtDone);
    unsubscribe();
  });

  it("preserves reasoning, tool arguments, results and speaker order", () => {
    const listener = vi.fn();
    const unsubscribe = subscribe(SESSION, listener);
    for (let i = 0; i < 100; i++) {
      ingestHarnessChunk(SESSION, { type: "reasoning", content: `${i},` });
    }
    const reasoningSnapshot = getSnapshot(SESSION);
    const args = '{"path":"report.txt"}';
    for (const fragment of args) {
      ingestHarnessChunk(SESSION, {
        type: "tool_call_chunk",
        id: "read",
        name: "read_file",
        args: fragment,
      });
    }
    expect(listener.mock.calls.length).toBeLessThanOrEqual(1);
    ingestHarnessChunk(SESSION, {
      type: "tool_result",
      node: "tools",
      messages: [{ tool_call_id: "read", content: "full report" }],
    });
    expect(listener).toHaveBeenCalledTimes(1);
    ingestHarnessChunk(SESSION, {
      type: "token",
      node: "agent",
      content: "expert answer",
      agent_id: "expert",
    });
    ingestHarnessChunk(SESSION, { type: "done", agent_id: "expert" });
    expect(getSnapshot(SESSION).messages.map((m) => m.speakerAgentId)).toEqual([
      undefined,
      undefined,
      "expert",
    ]);
    expect(reasoningSnapshot.messages[0].contentBlocks?.[0].content).toBe(
      Array.from({ length: 100 }, (_, i) => `${i},`).join(""),
    );
    expect(reasoningSnapshot.messages).toHaveLength(1);
    expect(getSnapshot(SESSION).messages[1].toolData).toMatchObject({
      arguments: args,
      output: "full report",
    });
    unsubscribe();
  });

  it.each(["error", "hitl_required"])("publishes %s immediately", (type) => {
    const listener = vi.fn();
    const unsubscribe = subscribe(SESSION, listener);
    ingestHarnessChunk(SESSION, {
      type: "token",
      node: "agent",
      content: "partial",
    });
    listener.mockClear();
    if (type === "error") {
      ingestHarnessChunk(SESSION, { type, message: "stopped" });
    } else {
      ingestHarnessChunk(SESSION, {
        type: "hitl_required",
        request: { actions: [] },
      });
    }
    expect(listener).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(64);
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it("publishes cancellation and history immediately without a delayed rebound", () => {
    const listener = vi.fn();
    const unsubscribe = subscribe(SESSION, listener);
    ingestHarnessChunk(SESSION, {
      type: "token",
      node: "agent",
      content: "partial",
    });
    listener.mockClear();
    cancelStream(SESSION);
    expect(listener).toHaveBeenCalledTimes(1);
    expect(getSnapshot(SESSION).messages[0].status).toBe("done");
    setHistoryPage(SESSION, [], { hasMore: false, nextOffset: 0 });
    const history = getSnapshot(SESSION);
    expect(listener).toHaveBeenCalledTimes(2);
    vi.advanceTimersByTime(64);
    expect(getSnapshot(SESSION)).toBe(history);
    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
  });

  it("cancels a queued empty token publication even before a bubble exists", () => {
    const listener = vi.fn();
    const unsubscribe = subscribe(SESSION, listener);
    ingestHarnessChunk(SESSION, { type: "token", node: "agent", content: "" });
    listener.mockClear();
    cancelStream(SESSION);
    expect(listener).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(64);
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it("isolates pending sessions and drops timers when the last observer leaves", () => {
    const first = vi.fn();
    const second = vi.fn();
    const unsubscribe = subscribe(SESSION, first);
    const unsubscribeOther = subscribe(OTHER, second);
    ingestHarnessChunk(SESSION, {
      type: "token",
      node: "agent",
      content: "first",
    });
    ingestHarnessChunk(OTHER, {
      type: "token",
      node: "agent",
      content: "other",
    });
    first.mockClear();
    second.mockClear();
    unsubscribe();
    vi.advanceTimersByTime(32);
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
    ingestHarnessChunk(SESSION, {
      type: "token",
      node: "agent",
      content: " unseen",
    });
    expect(getSnapshot(SESSION).messages[0].content).toBe("first unseen");
    expect(vi.getTimerCount()).toBe(0);
    unsubscribeOther();
  });

  it("publishes a newly focused session immediately and cleans up removed sessions", () => {
    setFocusedChatSession(OTHER);
    const listener = vi.fn();
    const unsubscribe = subscribe(SESSION, listener);
    ingestHarnessChunk(SESSION, {
      type: "token",
      node: "agent",
      content: "latest",
    });
    listener.mockClear();
    setFocusedChatSession(SESSION);
    expect(listener).toHaveBeenCalledTimes(1);
    ingestHarnessChunk(SESSION, {
      type: "token",
      node: "agent",
      content: " pending",
    });
    listener.mockClear();
    removeSession(SESSION);
    vi.advanceTimersByTime(64);
    expect(listener).not.toHaveBeenCalled();
    expect(getSnapshot(SESSION).messages).toEqual([]);
    unsubscribe();
  });
});
