import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import {
  taskCenterApi,
  type TaskOverviewPage,
} from "../api/modules/taskCenter";
import TaskOverview from "./TaskOverview";

vi.mock("../api/modules/taskCenter", () => ({
  taskCenterApi: { page: vi.fn() },
}));
vi.mock("../context/AgentContext", () => ({
  useAgent: () => ({
    agents: [
      { agent_id: "expert", name: "Research" },
      { agent_id: "other", name: "Writing" },
    ],
  }),
}));
vi.mock("../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "Asia/Shanghai",
}));

const page = (title = "Training"): TaskOverviewPage => ({
  items: [
    {
      id: "job:1",
      source_id: "1",
      source: "job",
      title,
      status: "running",
      lifecycle: "active",
      agent_id: "expert",
      agent_name: "Research",
      thread_id: "origin",
      thread_title: "Experiment",
      summary: "",
      updated_at: 1794538800,
      stale: false,
      declared: false,
    },
  ],
  total: 1,
  counts: { active: 1, all: 1 },
  offset: 0,
  limit: 20,
  has_more: false,
  agents: [{ value: "expert", label: "Research" }],
  threads: [{ value: "origin", label: "Experiment", agent_id: "expert" }],
  observed_at: 1794538800,
});
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(taskCenterApi.page).mockResolvedValue(page());
});

it("loads all conversations for one expert and opens the correct origin", async () => {
  const Probe = () => (
    <output data-testid="location">{useLocation().pathname}</output>
  );
  render(
    <MemoryRouter>
      <TaskOverview agentId="expert" fixedAgent />
      <Probe />
    </MemoryRouter>,
  );
  await screen.findByText("Training");
  expect(taskCenterApi.page).toHaveBeenCalledWith(
    expect.objectContaining({
      agent_id: "expert",
      thread_id: "",
      lifecycle: "active",
    }),
  );
  expect(
    screen.queryByRole("combobox", { name: "taskCenter.expert" }),
  ).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "taskCenter.openConversation" }),
  );
  expect(screen.getByTestId("location")).toHaveTextContent(
    "/chat/expert/origin",
  );
});

it("sends expert and conversation filters to the server and resets pagination", async () => {
  render(
    <MemoryRouter>
      <TaskOverview />
    </MemoryRouter>,
  );
  await screen.findByText("Training");
  fireEvent.mouseDown(
    screen.getByRole("combobox", { name: "taskCenter.expert" }),
  );
  fireEvent.click(
    await screen.findByText("Research", {
      selector: ".ant-select-item-option-content",
    }),
  );
  await waitFor(() =>
    expect(taskCenterApi.page).toHaveBeenLastCalledWith(
      expect.objectContaining({ agent_id: "expert", thread_id: "", offset: 0 }),
    ),
  );
  fireEvent.mouseDown(
    screen.getByRole("combobox", { name: "taskCenter.conversation" }),
  );
  fireEvent.click(
    await screen.findByText("Experiment", {
      selector: ".ant-select-item-option-content",
    }),
  );
  await waitFor(() =>
    expect(taskCenterApi.page).toHaveBeenLastCalledWith(
      expect.objectContaining({
        agent_id: "expert",
        thread_id: "origin",
        offset: 0,
      }),
    ),
  );
});

it("does not show a late response from a previously selected expert", async () => {
  let complete!: (value: TaskOverviewPage) => void;
  vi.mocked(taskCenterApi.page).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        complete = resolve;
      }),
  );
  const view = render(
    <MemoryRouter>
      <TaskOverview agentId="expert" fixedAgent />
    </MemoryRouter>,
  );
  await waitFor(() => expect(taskCenterApi.page).toHaveBeenCalledTimes(1));
  view.rerender(
    <MemoryRouter>
      <TaskOverview agentId="other" fixedAgent />
    </MemoryRouter>,
  );
  await screen.findByText("Training");
  complete(page("Old expert secret"));
  await waitFor(() =>
    expect(screen.queryByText("Old expert secret")).not.toBeInTheDocument(),
  );
});

it("loads archives only after explicit selection", async () => {
  render(
    <MemoryRouter>
      <TaskOverview />
    </MemoryRouter>,
  );
  await screen.findByText("Training");
  fireEvent.click(screen.getByText("taskFilters.archived"));
  await waitFor(() =>
    expect(taskCenterApi.page).toHaveBeenLastCalledWith(
      expect.objectContaining({ lifecycle: "archived" }),
    ),
  );
  expect(
    within(screen.getByRole("list")).getByText("Training"),
  ).toBeInTheDocument();
});
