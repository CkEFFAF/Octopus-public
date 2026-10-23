import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { activityApi } from "../../../api/modules/activity";
import ExpertTaskSummary from "./ExpertTaskSummary";

vi.mock("../hooks/useSidebarActivity", () => ({
  useSidebarActivity: () => ({
    expert: {
      working_threads: [
        {
          thread_id: "chat",
          title: "**实验迁移结果**",
          metadata: { current_progress: "正在检查对照差异" },
        },
      ],
      background_tasks: Array.from({ length: 3 }, (_, index) => ({
        id: `${index}`,
        thread_id: "chat",
        name: "62c20c0ff8579cc79b5e12ccba4f5a05",
        stale: false,
      })),
    },
  }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { resolvedLanguage: "zh" },
  }),
}));

it("keeps IDs and event streams out of the summary, with bounded details in place", async () => {
  const snapshot = vi.spyOn(activityApi, "snapshot").mockResolvedValue({
    nodes: Array.from({ length: 30 }, (_, i) => ({
      id: `${i}`,
      type: "tool",
      name: "command.run",
      status: "completed",
      updated_at: i + 1,
      dependencies_known: false,
    })),
    edges: [],
    observed_at: 1,
    scope_truncated: false,
    next_before: null,
    counts: { subagents: 0, jobs: 3, parallel: null, completed: 30 },
  });
  render(
    <MemoryRouter>
      <ExpertTaskSummary agentId="expert" />
    </MemoryRouter>,
  );
  expect(screen.getByText("实验迁移结果")).toBeVisible();
  expect(screen.getByText("正在检查对照差异")).toBeVisible();
  expect(screen.queryByText("62c20c0ff8579cc79b5e12ccba4f5a05")).toBeNull();
  expect(snapshot).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "sessionPreview.taskDetails" }),
  );
  const dialog = await screen.findByRole("dialog");
  expect(
    within(dialog).getAllByText("sessionPreview.toolCommand"),
  ).toHaveLength(8);
  expect(within(dialog).queryByText("command.run")).toBeNull();
  fireEvent.click(
    within(dialog).getByRole("button", { name: "sessionPreview.olderRecords" }),
  );
  expect(
    within(dialog).getAllByText("sessionPreview.toolCommand"),
  ).toHaveLength(16);
  snapshot.mockRestore();
});
