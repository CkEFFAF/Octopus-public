import { afterEach, expect, it, vi } from "vitest";
import {
  attachThread,
  getSnapshot,
  onStreamEvent,
  removeSession,
  setFocusedChatSession,
} from "./chatStore";

vi.mock("../../../api/modules/wsChat", () => ({
  buildDashboardChatWsUrl: () => "ws://localhost/test",
}));
const sockets: Socket[] = [];
const frames: Record<string, unknown>[] = [];
let turnActive = false;
class Socket {
  static OPEN = 1;
  static CONNECTING = 0;
  readyState = 1;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() {
    sockets.push(this);
    queueMicrotask(() => this.onopen?.());
  }
  send(data: string) {
    const frame = JSON.parse(data);
    frames.push(frame);
    if (frame.type === "subscribe")
      queueMicrotask(
        () =>
          this.onmessage?.({
            data: JSON.stringify({
              type: "turn_status",
              active: turnActive,
              input_controls: true,
            }),
          }),
      );
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
}
afterEach(() => {
  removeSession("idle-reconnect");
  setFocusedChatSession(null);
  sockets.length = 0;
  frames.length = 0;
  turnActive = false;
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
it("reconnects an idle visible thread with subscribe only", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", Socket);
  setFocusedChatSession("idle-reconnect");
  await attachThread("idle-reconnect", "agent", "idle-reconnect");
  expect(getSnapshot("idle-reconnect").isStreaming).toBe(false);
  sockets[0].close();
  await vi.advanceTimersByTimeAsync(450);
  expect(sockets).toHaveLength(2);
  expect(frames.filter((frame) => frame.type === "subscribe")).toHaveLength(2);
  expect(
    frames.some(
      (frame) => frame.type === "cancel" || frame.type === "user_turn",
    ),
  ).toBe(false);
  expect(getSnapshot("idle-reconnect").isStreaming).toBe(false);
});

it("requests a fresh authoritative status on an existing idle subscription", async () => {
  vi.stubGlobal("WebSocket", Socket);
  await attachThread("idle-reconnect", "agent", "idle-reconnect");
  await attachThread(
    "idle-reconnect",
    "agent",
    "idle-reconnect",
    undefined,
    0,
    { refreshStatus: true },
  );
  expect(sockets).toHaveLength(1);
  expect(frames.map((frame) => frame.type)).toEqual(["subscribe", "subscribe"]);
});

it("emits one recovery notice when periodic status checks reuse a resumed socket", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", Socket);
  setFocusedChatSession("idle-reconnect");
  turnActive = true;
  const listener = vi.fn();
  const unsubscribe = onStreamEvent(listener);

  try {
    await attachThread("idle-reconnect", "agent", "idle-reconnect");
    sockets[0].close();
    await vi.advanceTimersByTimeAsync(450);
    expect(sockets).toHaveLength(2);
    expect(getSnapshot("idle-reconnect").isStreaming).toBe(true);

    for (let index = 0; index < 3; index += 1) {
      await attachThread(
        "idle-reconnect",
        "agent",
        "idle-reconnect",
        undefined,
        0,
        {
          refreshStatus: true,
        },
      );
    }

    expect(sockets).toHaveLength(2);
    expect(
      listener.mock.calls.filter(([event]) => event.kind === "streamResume"),
    ).toHaveLength(1);
    expect(frames.every((frame) => frame.type === "subscribe")).toBe(true);
  } finally {
    unsubscribe();
  }
});

it.each([false, true])(
  "does not report a later turn after an idle status on reconnect (previously active: %s)",
  async (wasActive) => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", Socket);
    setFocusedChatSession("idle-reconnect");
    turnActive = wasActive;
    const listener = vi.fn();
    const unsubscribe = onStreamEvent(listener);

    try {
      await attachThread("idle-reconnect", "agent", "idle-reconnect");
      expect(getSnapshot("idle-reconnect").isStreaming).toBe(wasActive);
      sockets[0].close();
      turnActive = false;
      await vi.advanceTimersByTimeAsync(450);
      expect(sockets).toHaveLength(2);
      expect(getSnapshot("idle-reconnect").isStreaming).toBe(false);

      turnActive = true;
      await attachThread(
        "idle-reconnect",
        "agent",
        "idle-reconnect",
        undefined,
        0,
        {
          refreshStatus: true,
        },
      );

      expect(getSnapshot("idle-reconnect").isStreaming).toBe(true);
      expect(listener).not.toHaveBeenCalledWith({
        kind: "streamResume",
        sessionId: "idle-reconnect",
      });
    } finally {
      unsubscribe();
    }
  },
);
