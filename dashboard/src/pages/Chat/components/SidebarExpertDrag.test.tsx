import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import SidebarExpertDrag, { SidebarDragHandle } from "./SidebarExpertDrag";
import { useExpertOrder } from "../hooks/useExpertOrder";
vi.mock("../../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ id: 891 }),
}));
function Fixture() {
  const { order } = useExpertOrder();
  const agents = order([{ agent_id: "a" }, { agent_id: "b" }]);
  return (
    <SidebarExpertDrag ids={agents.map((a) => a.agent_id)}>
      <div data-sidebar-zone="pinned" data-testid="pin" />
      <div data-sidebar-zone="main">
        {agents.map((agent) => (
          <div
            key={agent.agent_id}
            data-sidebar-expert={agent.agent_id}
            data-testid={agent.agent_id}
          >
            <SidebarDragHandle />
            {agent.agent_id}
          </div>
        ))}
      </div>
    </SidebarExpertDrag>
  );
}
beforeEach(() => {
  localStorage.clear();
  vi.useFakeTimers();
  window.PointerEvent = MouseEvent as typeof PointerEvent;
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});
it("persists keyboard reorder and pin changes without activating a chat", () => {
  render(<Fixture />);
  const handle = screen.getByTestId("b").querySelector("button")!;
  fireEvent.keyDown(handle, { key: "ArrowUp", altKey: true });
  expect(JSON.parse(localStorage.getItem("octop:expert-order:891")!)).toEqual([
    "b",
    "a",
  ]);
  fireEvent.keyDown(handle, { key: "p", altKey: true });
  expect(JSON.parse(localStorage.getItem("octop:pinned-experts:891")!)).toEqual(
    ["b"],
  );
});
it("requires a hold, then pins when released over the empty top zone", () => {
  render(<Fixture />);
  const handle = screen.getByTestId("b").querySelector("button")!;
  Object.defineProperty(document, "elementFromPoint", {
    configurable: true,
    value: () => screen.getByTestId("pin"),
  });
  const down = new MouseEvent("pointerdown", {
    bubbles: true,
    button: 0,
    clientX: 20,
    clientY: 100,
  });
  Object.defineProperties(down, {
    isPrimary: { value: true },
    pointerId: { value: 1 },
  });
  fireEvent(handle, down);
  act(() => vi.advanceTimersByTime(450));
  const up = new MouseEvent("pointerup", {
    bubbles: true,
    clientX: 20,
    clientY: 10,
  });
  Object.defineProperty(up, "pointerId", { value: 1 });
  fireEvent(handle, up);
  expect(JSON.parse(localStorage.getItem("octop:pinned-experts:891")!)).toEqual(
    ["b"],
  );
});
