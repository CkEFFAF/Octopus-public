import { afterEach, describe, expect, it, vi } from "vitest";
import { removeSession, sendTurn } from "./chatStore";

vi.mock("../../../api/modules/wsChat", () => ({
  buildDashboardChatWsUrl: () => "ws://localhost/test-chat",
}));

const turns: Record<string, unknown>[] = [];
class Socket {
  static OPEN = 1;
  static CONNECTING = 0;
  static CLOSED = 3;
  readyState = 1;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  constructor() {
    queueMicrotask(() => this.onopen?.());
  }
  send(data: string) {
    const frame = JSON.parse(data);
    if (frame.type !== "user_turn") return;
    turns.push(frame);
    queueMicrotask(
      () =>
        this.onmessage?.({
          data: JSON.stringify({ type: "done", thread_id: "device-thread" }),
        }),
    );
  }
  close() {
    this.readyState = 3;
    this.onclose?.({ code: 1000 });
  }
}

afterEach(() => {
  removeSession("device-thread");
  turns.length = 0;
  vi.unstubAllGlobals();
});

describe("chat target device", () => {
  it.each(["device-a", undefined, ""])(
    "sends only the device selected for this turn: %s",
    async (device) => {
      vi.stubGlobal("WebSocket", Socket);
      await sendTurn(
        "device-thread",
        "Read shared files",
        "agent",
        "agent:dashboard:1",
        undefined,
        undefined,
        undefined,
        "device-thread",
        [],
        [],
        [],
        undefined,
        undefined,
        "craft",
        undefined,
        device,
      );
      expect(turns).toHaveLength(1);
      expect(turns[0].device_id).toBe(device || undefined);
      if (!device) expect(turns[0].target_kind).toBeUndefined();
      expect(turns[0].messages).toEqual([
        { role: "user", content: "Read shared files" },
      ]);
    },
  );
});
