import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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
    list: vi.fn(async () => []),
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
