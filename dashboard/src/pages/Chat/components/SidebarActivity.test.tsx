import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { ConfigProvider } from "antd";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  octopThreadsApi,
  type SidebarStatus,
} from "../../../api/modules/octopThreads";
import type { OctopAgent } from "../../../context/AgentContext";
import { toSession } from "../hooks/useSessions";
import SessionList from "./SessionList";
import MinimalAgentSessionNav from "./MinimalAgentSessionNav";

let userId = 1;
vi.mock("../../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ id: userId }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
const agent = {
  id: 1,
  agent_id: "expert",
  name: "Expert",
  state: "running",
} as OctopAgent;
const idle = toSession({
  thread_id: "selected",
  title: "Selected idle chat",
  is_active: true,
  last_active: 1,
});
const status: SidebarStatus = {
  working_threads: [
    {
      thread_id: "old-background",
      title: "Older background chat",
      channel_type: "dashboard",
      last_active: 0,
      created_at: 1,
      pinned: false,
    },
  ],
  schedules: [
    {
      thread_id: "old-background",
      id: "daily",
      name: "Daily check",
      enabled: true,
      scheduler_state: "scheduled",
      next_run_at: 1800000000,
      timezone: "Asia/Shanghai",
    },
    {
      thread_id: "selected",
      id: "paused",
      name: "Paused check",
      enabled: false,
      scheduler_state: "paused",
      next_run_at: null,
      timezone: "Asia/Shanghai",
    },
  ],
};
const common = {
  agents: [agent],
  activeAgentId: "expert",
  activeId: "selected",
  onSelect: vi.fn(),
  onAgentSelect: vi.fn(),
  onNewChat: vi.fn(),
  onFork: vi.fn(),
};
function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="location">
      {location.pathname}
      {location.search}
    </output>
  );
}
function classic() {
  return (
    <ConfigProvider prefixCls="octop">
      <MemoryRouter>
        <LocationProbe />
        <SessionList
          {...common}
          sessions={[idle]}
          hasMore={false}
          loadingMore={false}
          onLoadMore={vi.fn()}
          onFetchAllSessions={vi.fn()}
          onDelete={vi.fn()}
          onRename={vi.fn()}
          onPin={vi.fn()}
        />
      </MemoryRouter>
    </ConfigProvider>
  );
}
beforeEach(() => {
  userId = 1;
  vi.spyOn(octopThreadsApi, "sidebarStatus").mockResolvedValue(status);
  vi.spyOn(octopThreadsApi, "list").mockResolvedValue([]);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("exposes working chats under other experts without switching experts first", async () => {
  const other = { ...agent, id: 2, agent_id: "other", name: "Other expert" };
  vi.mocked(octopThreadsApi.sidebarStatus).mockImplementation(async (id) =>
    id === "other" ? status : { working_threads: [], schedules: [] },
  );
  common.onSelect.mockClear();
  render(
    <MemoryRouter>
      <SessionList
        {...common}
        agents={[agent, other]}
        sessions={[idle]}
        hasMore={false}
        loadingMore={false}
        onLoadMore={vi.fn()}
        onFetchAllSessions={vi.fn()}
        onDelete={vi.fn()}
        onRename={vi.fn()}
        onPin={vi.fn()}
      />
    </MemoryRouter>,
  );
  const title = await screen.findByText("Older background chat");
  fireEvent.click(title);
  expect(common.onSelect).toHaveBeenCalledWith("old-background", "other");
});

it("shows background activity and schedule states without treating selection as work", async () => {
  const view = render(classic());
  const row = (await screen.findByText("Older background chat")).closest(
    '[role="button"]',
  ) as HTMLElement;
  expect(within(row).getByText("chat.sessionWorkingShort")).toBeVisible();
  expect(row.className).toMatch(/sessionRowWorking/);
  const scheduled = within(row).getByLabelText("chat.sessionSchedules");
  expect(scheduled).toHaveAttribute("data-scheduled", "true");
  expect(scheduled).not.toHaveAttribute("title");
  fireEvent.focus(scheduled);
  const details = await screen.findByRole("tooltip");
  expect(details.className).toContain("octop-tooltip-inner");
  expect(details.style.color).toBe("var(--fn-text-primary)");
  expect(details).toHaveTextContent("Daily check");
  expect(details).toHaveTextContent("2027");
  expect(details).toHaveTextContent("Asia/Shanghai");
  fireEvent.blur(scheduled);
  common.onSelect.mockClear();
  fireEvent.keyDown(scheduled, { key: "Enter" });
  expect(common.onSelect).not.toHaveBeenCalled();
  expect(screen.getByTestId("location")).toHaveTextContent(
    "/chat/expert/old-background?task_view=schedules",
  );
  const selected = screen
    .getByText("Selected idle chat")
    .closest('[role="button"]') as HTMLElement;
  expect(within(selected).queryByText("chat.sessionWorkingShort")).toBeNull();
  expect(
    within(selected).getByLabelText("chat.sessionSchedules"),
  ).toHaveAttribute("data-scheduled", "false");
  vi.mocked(octopThreadsApi.sidebarStatus).mockResolvedValue({
    working_threads: [],
    schedules: [],
  });
  fireEvent(document, new Event("visibilitychange"));
  await waitFor(() =>
    expect(screen.queryByText("chat.sessionWorkingShort")).toBeNull(),
  );
  expect(screen.queryByLabelText("chat.sessionSchedules")).toBeNull();
  view.unmount();
});

it("limits hover to the two nearest schedules and clicks through to this chat's workbench", async () => {
  vi.mocked(octopThreadsApi.sidebarStatus).mockResolvedValue({
    working_threads: [],
    schedules: [
      {
        ...status.schedules[1],
        id: "next",
        enabled: true,
        scheduler_state: "scheduled",
        name: "Next check",
        next_run_at: 1800000200,
      },
      {
        ...status.schedules[1],
        id: "sooner",
        enabled: true,
        scheduler_state: "scheduled",
        name: "Sooner check",
        next_run_at: 1800000000,
      },
      ...Array.from({ length: 40 }, (_, i) => ({
        ...status.schedules[1],
        id: `old-${i}`,
        name: `Archived check ${i}`,
        scheduler_state: "exhausted",
        last_run_at: 1700000000 + i,
      })),
    ],
  });
  render(classic());
  const badge = await screen.findByRole("button", {
    name: "chat.sessionSchedules",
  });
  fireEvent.mouseEnter(badge);
  const preview = await screen.findByRole("tooltip");
  expect(within(preview).getAllByRole("listitem")).toHaveLength(2);
  expect(within(preview).queryByText("Archived check 0")).toBeNull();
  await waitFor(() =>
    expect(within(preview).getByText("Sooner check")).toBeVisible(),
  );
  expect(within(preview).getByText("Next check")).toBeVisible();
  common.onSelect.mockClear();
  fireEvent.click(badge);
  expect(common.onSelect).not.toHaveBeenCalled();
  expect(screen.getByTestId("location")).toHaveTextContent(
    "/chat/expert/selected?task_view=schedules",
  );
});

it("previews the latest past reminders with actual fire times and opens the reminders page", async () => {
  vi.mocked(octopThreadsApi.sidebarStatus).mockResolvedValue({
    working_threads: [],
    schedules: Array.from({ length: 8 }, (_, i) => ({
      ...status.schedules[1],
      id: `reminder-${i}`,
      name: `Past reminder ${i}`,
      self_reminder: true,
      scheduler_state: "exhausted",
      last_run_at: 1700000000 + i * 60,
    })),
  });
  render(classic());
  const badge = await screen.findByRole("button", {
    name: "chat.sessionSchedules",
  });
  fireEvent.focus(badge);
  const preview = await screen.findByRole("tooltip");
  expect(within(preview).getAllByRole("listitem")).toHaveLength(2);
  await waitFor(() =>
    expect(within(preview).getByText("Past reminder 7")).toBeVisible(),
  );
  expect(within(preview).getByText("Past reminder 6")).toBeVisible();
  expect(preview).toHaveTextContent("2023");
  expect(preview).toHaveTextContent("chat.sessionScheduleLastRun");
  fireEvent.keyDown(badge, { key: " " });
  expect(screen.getByTestId("location")).toHaveTextContent(
    "/chat/expert/selected?task_view=reminders",
  );
});

it("also exposes an older running conversation in minimal previews", async () => {
  render(
    <MemoryRouter>
      <MinimalAgentSessionNav
        {...common}
        activeSessions={[idle]}
        onDeleteActive={vi.fn()}
        onRenameActive={vi.fn()}
        onPinActive={vi.fn()}
      />
    </MemoryRouter>,
  );
  const row = (await screen.findByText("Older background chat")).closest(
    '[role="button"]',
  ) as HTMLElement;
  expect(within(row).getByText("chat.sessionWorkingShort")).toBeVisible();
  expect(within(row).getByLabelText("chat.sessionSchedules")).toHaveAttribute(
    "data-scheduled",
    "true",
  );
});

it("discards a late observation from the previous signed-in account", async () => {
  let finish!: (value: SidebarStatus) => void;
  vi.mocked(octopThreadsApi.sidebarStatus).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const view = render(classic());
  userId = 2;
  vi.mocked(octopThreadsApi.sidebarStatus).mockResolvedValue({
    working_threads: [],
    schedules: [],
  });
  view.rerender(classic());
  await act(async () => {
    finish(status);
  });
  expect(screen.queryByText("Older background chat")).toBeNull();
  expect(screen.queryByLabelText("chat.sessionSchedules")).toBeNull();
});
