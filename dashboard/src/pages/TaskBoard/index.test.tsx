import type { ReactNode } from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TaskBoardPage from "./index";
import { taskBoardApi, type BoardSnapshot } from "../../api/modules/taskBoard";
import { taskCenterApi } from "../../api/modules/taskCenter";

vi.mock("../../layouts/PageShell", () => ({
  default: ({
    children,
    actions,
  }: {
    children: ReactNode;
    actions: ReactNode;
  }) => (
    <div>
      {actions}
      {children}
    </div>
  ),
}));
vi.mock("../../context/AgentContext", () => ({
  useAgent: () => ({ agents: [] }),
}));
vi.mock("../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "Asia/Shanghai",
}));
vi.mock("../../api/modules/taskBoard", () => ({
  taskBoardApi: { get: vi.fn(), act: vi.fn(), parse: vi.fn() },
}));
vi.mock("../../api/modules/taskCenter", () => ({
  taskCenterApi: { page: vi.fn() },
}));
vi.mock("../../api/modules/teams", () => ({
  teamsApi: {
    list: vi
      .fn()
      .mockResolvedValue([
        { team_id: "project-1", name: "Project one", member_ids: [] },
      ]),
  },
}));
vi.mock("../../api/modules/devices", () => ({
  devicesApi: { list: vi.fn().mockResolvedValue({ devices: [] }) },
}));
vi.mock("../../api/modules/provider", () => ({
  providerApi: { listResolvedModels: vi.fn().mockResolvedValue([]) },
}));
vi.mock("@/utils/antdMessage", () => ({
  message: { error: vi.fn(), warning: vi.fn() },
}));

const board: BoardSnapshot = {
  revision: 1,
  timezone: "Asia/Shanghai",
  tasks: [],
  tag_prefixes: {},
};
function Location() {
  return <output data-testid="location">{useLocation().search}</output>;
}
function show(path = "/task-board") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <TaskBoardPage />
      <Location />
    </MemoryRouter>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(taskBoardApi.get).mockResolvedValue(board);
  vi.mocked(taskCenterApi.page).mockResolvedValue({
    items: [],
    total: 0,
    counts: {},
    offset: 0,
    limit: 100,
    has_more: false,
    agents: [],
    threads: [],
    observed_at: 0,
  });
});

describe("task board recovery and form protection", () => {
  it("stops ledger polling in archives and refreshes both data sources on demand", async () => {
    const interval = vi.spyOn(window, "setInterval");
    const clear = vi.spyOn(window, "clearInterval");
    try {
      show();
      await waitFor(() => expect(taskBoardApi.get).toHaveBeenCalled());
      const timerIndex = interval.mock.calls.findIndex(
        (call) => call[1] === 5000,
      );
      expect(timerIndex).toBeGreaterThanOrEqual(0);
      const timer = interval.mock.results[timerIndex].value;
      fireEvent.click(screen.getByRole("button", { name: /octopus.archive/ }));
      await waitFor(() =>
        expect(taskCenterApi.page).toHaveBeenLastCalledWith(
          expect.objectContaining({ lifecycle: "archived" }),
        ),
      );
      expect(clear).toHaveBeenCalledWith(timer);
      expect(
        interval.mock.calls.filter((call) => call[1] === 5000),
      ).toHaveLength(1);
      const count = vi.mocked(taskCenterApi.page).mock.calls.length;
      const ledgerCount = vi.mocked(taskBoardApi.get).mock.calls.length;
      fireEvent.click(screen.getByRole("button", { name: "octopus.refresh" }));
      await waitFor(() =>
        expect(taskCenterApi.page).toHaveBeenCalledTimes(count + 1),
      );
      expect(taskBoardApi.get).toHaveBeenCalledTimes(ledgerCount + 1);
    } finally {
      interval.mockRestore();
      clear.mockRestore();
    }
  });

  it("automatically places live execution tasks in the corresponding board column", async () => {
    vi.mocked(taskCenterApi.page).mockResolvedValue({
      items: [
        {
          id: "job:live",
          source_id: "live",
          source: "job",
          title: "Training in another conversation",
          status: "running",
          lifecycle: "active",
          agent_id: "expert",
          agent_name: "Research",
          thread_id: "origin",
          thread_title: "Experiment",
          updated_at: 1794538800,
          summary: "",
          stale: false,
          declared: false,
        },
      ],
      total: 1,
      counts: { active: 1 },
      offset: 0,
      limit: 100,
      has_more: false,
      agents: [],
      threads: [],
      observed_at: 0,
    });
    show();
    await screen.findByText("Training in another conversation");
    expect(
      within(screen.getByRole("region", { name: "octopus.running" })).getByText(
        "Training in another conversation",
      ),
    ).toBeInTheDocument();
    expect(taskBoardApi.act).not.toHaveBeenCalled();
    expect(taskCenterApi.page).toHaveBeenCalledWith(
      expect.objectContaining({ include_board: false }),
    );
  });
  it("distinguishes no matches and clears filters while retaining project and unrelated URL parameters", async () => {
    show("/task-board?project=project-1&agent=missing-agent&context=keep");
    await screen.findByText("uiFeedback.noMatchingTasks");
    fireEvent.click(
      screen.getByRole("button", { name: "octopus.clearFilters" }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("location")).not.toHaveTextContent("agent="),
    );
    expect(screen.getByTestId("location")).toHaveTextContent(
      "project=project-1",
    );
    expect(screen.getByTestId("location")).toHaveTextContent("context=keep");
    expect(
      screen.queryByText("uiFeedback.noMatchingTasks"),
    ).not.toBeInTheDocument();
    expect(taskBoardApi.act).not.toHaveBeenCalled();
  });
  it("protects AI draft input and retains it when closing is canceled", async () => {
    show("/task-board?project=project-1&new=1&context=keep");
    const editor = await screen.findByRole("dialog");
    expect(within(editor).getByText("Project one")).toBeInTheDocument();
    const draft = within(editor).getByPlaceholderText("octopus.aiPlaceholder");
    fireEvent.change(draft, { target: { value: "Keep my draft" } });
    expect(
      window.dispatchEvent(new Event("beforeunload", { cancelable: true })),
    ).toBe(false);
    fireEvent.click(within(editor).getByRole("button", { name: "Close" }));
    const keepEditing = await screen.findByRole("button", {
      name: "uiFeedback.keepEditing",
    });
    fireEvent.click(keepEditing);
    expect(draft).toHaveValue("Keep my draft");
    expect(screen.getByTestId("location")).toHaveTextContent("context=keep");
    expect(taskBoardApi.act).not.toHaveBeenCalled();
    expect(taskBoardApi.parse).not.toHaveBeenCalled();
  });
});
