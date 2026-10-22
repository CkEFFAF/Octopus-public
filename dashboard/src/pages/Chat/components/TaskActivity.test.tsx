import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import {
  activityApi,
  type ActivitySnapshot,
} from "../../../api/modules/activity";
import TaskActivity from "./TaskActivity";
vi.mock("../../../api/modules/activity", () => ({
  activityApi: {
    snapshot: vi.fn(async () => ({
      nodes: [],
      edges: [],
      observed_at: Date.now() / 1000,
      scope_truncated: false,
      next_before: null,
      counts: { subagents: 0, jobs: 0, parallel: null, completed: 0 },
    })),
  },
}));
vi.mock("../../../api/modules/cronjob", () => ({
  octopCronApi: {
    page: vi.fn(async () => ({
      items: [],
      total: 0,
      has_more: false,
      next_offset: null,
      counts: { schedules: 0, reminders: 0 },
    })),
    attempts: vi.fn(async () => ({
      items: [],
      has_more: false,
      next_cursor: null,
    })),
  },
}));
vi.mock("../../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "Asia/Shanghai",
}));
vi.mock("./TaskActivityGraph", () => ({ default: () => <div /> }));
describe("task workbench entry", () => {
  it.each(["schedules", "reminders"])(
    "opens the requested %s page for the matching chat and clears the link on close",
    async (tab) => {
      function LocationProbe() {
        const location = useLocation();
        return (
          <output data-testid="workbench-location">{location.search}</output>
        );
      }
      const view = render(
        <MemoryRouter initialEntries={[`/chat/a/t?task_view=${tab}&keep=1`]}>
          <Routes>
            <Route
              path="/chat/:agentId/:threadId"
              element={
                <>
                  <TaskActivity agentId="a" threadId="t" />
                  <LocationProbe />
                </>
              }
            />
          </Routes>
        </MemoryRouter>,
      );
      await waitFor(() => expect(screen.getByRole("dialog")).toBeVisible());
      expect(
        screen.getByRole("button", {
          name: new RegExp(`workspace0034.${tab}`),
        }),
      ).toHaveAttribute("aria-current", "page");
      fireEvent.click(screen.getByRole("button", { name: "common.close" }));
      expect(screen.getByTestId("workbench-location")).toHaveTextContent(
        "?keep=1",
      );
      view.unmount();
    },
  );

  it("does not open a different expert's workbench from a schedule link", async () => {
    const view = render(
      <MemoryRouter initialEntries={["/chat/other/t?task_view=schedules"]}>
        <Routes>
          <Route
            path="/chat/:agentId/:threadId"
            element={<TaskActivity agentId="a" threadId="t" />}
          />
        </Routes>
      </MemoryRouter>,
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    view.unmount();
  });
  it("delays mouse summary, and double click opens one workbench without summary", async () => {
    vi.useFakeTimers();
    const { unmount } = render(
      <MemoryRouter>
        <TaskActivity agentId="a" threadId="t" />
      </MemoryRouter>,
    );
    await act(async () => {
      await Promise.resolve();
    });
    const entry = screen.getByRole("button", { name: "workspace0034.tasks" });
    fireEvent.click(entry, { detail: 1 });
    expect(screen.queryByText("workspace0034.openWorkbench")).toBeNull();
    fireEvent.click(entry, { detail: 2 });
    fireEvent.doubleClick(entry);
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(screen.queryByText("workspace0034.openWorkbench")).toBeNull();
    expect(screen.getByText("workspace0034.liveScene")).toBeTruthy();
    unmount();
    vi.useRealTimers();
  });
  it("keyboard click opens accessible summary immediately", async () => {
    vi.useFakeTimers();
    const { unmount } = render(
      <MemoryRouter>
        <TaskActivity agentId="a" threadId="t" compact />
      </MemoryRouter>,
    );
    await act(async () => {
      await Promise.resolve();
    });
    fireEvent.click(
      screen.getByRole("button", { name: "workspace0034.tasks" }),
      { detail: 0 },
    );
    expect(screen.getByText("workspace0034.openWorkbench")).toBeTruthy();
    unmount();
    vi.useRealTimers();
  });
  it("does not merge a previous conversation history page into a new conversation", async () => {
    let resolveHistory: (value: ActivitySnapshot) => void = () => {};
    const empty = (next: number | null = null): ActivitySnapshot => ({
      nodes: [],
      edges: [],
      observed_at: Date.now() / 1000,
      scope_truncated: next !== null,
      next_before: next,
      counts: { subagents: 0, jobs: 0, parallel: null, completed: 0 },
    });
    vi.mocked(activityApi.snapshot).mockImplementation(
      async (_a, _t, before) =>
        before
          ? await new Promise((resolve) => {
              resolveHistory = resolve;
            })
          : empty(_t === "old" ? 10 : null),
    );
    const { rerender, unmount } = render(
      <MemoryRouter>
        <TaskActivity agentId="a" threadId="old" />
      </MemoryRouter>,
    );
    await act(async () => {
      await Promise.resolve();
    });
    fireEvent.doubleClick(
      screen.getByRole("button", { name: "workspace0034.tasks" }),
    );
    fireEvent.click(screen.getByText("devices.native.more"));
    rerender(
      <MemoryRouter>
        <TaskActivity agentId="a" threadId="new" />
      </MemoryRouter>,
    );
    await act(async () => {
      await Promise.resolve();
      resolveHistory({
        ...empty(),
        nodes: [
          {
            id: "late",
            name: "Late history from old",
            type: "tool",
            status: "completed",
            updated_at: 1,
            dependencies_known: false,
          },
        ],
      });
    });
    expect(screen.queryByText("Late history from old")).toBeNull();
    unmount();
  });
  it("does not call an accepted-only invocation running", async () => {
    vi.mocked(activityApi.snapshot).mockResolvedValue({
      nodes: [
        {
          id: "accepted",
          name: "Queued expert",
          type: "delegation",
          status: "accepted",
          observed_status: "current",
          updated_at: Date.now() / 1000,
          dependencies_known: false,
        },
      ],
      edges: [],
      observed_at: Date.now() / 1000,
      scope_truncated: false,
      next_before: null,
      counts: { subagents: 1, jobs: 0, parallel: null, completed: 0 },
    });
    const { unmount } = render(
      <MemoryRouter>
        <TaskActivity agentId="a" threadId="waiting" />
      </MemoryRouter>,
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(
      screen.getByRole("button", { name: "workspace0034.waitingAgents" }),
    ).toBeTruthy();
    expect(screen.queryByText("workspace0034.runningAgents")).toBeNull();
    unmount();
  });
});
