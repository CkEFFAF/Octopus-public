import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useDashboardPushToast } from "./useDashboardPushToast";
const mocks = vi.hoisted(() => ({
  open: vi.fn(),
  destroy: vi.fn(),
  refresh: vi.fn(),
  invalidate: vi.fn(),
  emit: vi.fn(),
}));
vi.mock("antd", () => ({
  App: {
    useApp: () => ({
      notification: { open: mocks.open, destroy: mocks.destroy },
    }),
  },
}));
vi.mock("../context/AgentContext", () => ({
  useAgent: () => ({ agents: [], refresh: mocks.refresh }),
}));
vi.mock("../api/request", () => ({ getAuthToken: () => "test" }));
vi.mock("../api/modules/wsNotifications", () => ({
  buildDashboardNotifyWsUrl: () => "ws://localhost/notify",
}));
vi.mock("../pages/Chat/hooks/chatStore", () => ({
  invalidateHistory: mocks.invalidate,
  emitSessionEvent: mocks.emit,
}));
let socket: FakeSocket;
class FakeSocket {
  static OPEN = 1;
  readyState = 1;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor() {
    // This fake exposes the newly constructed socket to the frame sender.
    // eslint-disable-next-line @typescript-eslint/no-this-alias
    socket = this;
  }
  send() {}
  close() {}
}
function Host() {
  useDashboardPushToast();
  const navigate = useNavigate();
  return (
    <button onClick={() => navigate("/chat/main/other")}>Open other</button>
  );
}
function push(thread: string) {
  act(
    () =>
      socket.onmessage?.({
        data: JSON.stringify({
          type: "dashboard_push",
          agent_id: "main",
          thread_id: thread,
          text: "Actual reminder output",
        }),
      }),
  );
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});
describe("dashboard push visibility", () => {
  it("refreshes visible current history without a toast and keeps other-thread notices", () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    render(
      <MemoryRouter initialEntries={["/chat/main/current"]}>
        <Host />
      </MemoryRouter>,
    );
    push("current");
    expect(mocks.invalidate).toHaveBeenCalledWith("current");
    expect(mocks.emit).toHaveBeenCalled();
    expect(mocks.open).not.toHaveBeenCalled();
    push("other");
    push("third");
    expect(mocks.open).toHaveBeenCalledTimes(2);
    const otherKey = mocks.open.mock.calls[0][0].key;
    fireEvent.click(screen.getByText("Open other"));
    expect(mocks.destroy).toHaveBeenCalledExactlyOnceWith(otherKey);
    expect(mocks.destroy).not.toHaveBeenCalledWith();
  });
  it("keeps background notices then clears only its thread on becoming visible", () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    let hidden = true;
    vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
    render(
      <MemoryRouter initialEntries={["/chat/main/current"]}>
        <Host />
      </MemoryRouter>,
    );
    push("current");
    push("other");
    const currentKey = mocks.open.mock.calls[0][0].key;
    hidden = false;
    fireEvent(document, new Event("visibilitychange"));
    expect(mocks.destroy).toHaveBeenCalledExactlyOnceWith(currentKey);
  });
});
