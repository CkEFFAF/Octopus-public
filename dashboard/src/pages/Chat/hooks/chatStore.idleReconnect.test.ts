import { afterEach, expect, it, vi } from "vitest";
import {
  attachThread,
  getSnapshot,
  removeSession,
  setFocusedChatSession,
} from "./chatStore";

vi.mock("../../../api/modules/wsChat", () => ({
  buildDashboardChatWsUrl: () => "ws://localhost/test",
}));
const sockets: Socket[] = [];
const frames: Record<string, unknown>[] = [];
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
              active: false,
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
