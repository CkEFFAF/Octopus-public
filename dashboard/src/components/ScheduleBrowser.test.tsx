import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { octopCronApi, type CronAttemptPage } from "../api/modules/cronjob";
import type { OctopCronRow } from "../api/types";
import styles from "./ScheduleBrowser.module.less";
const device = vi.hoisted(() => ({ mobile: false }));
vi.mock("../hooks/useIsMobile", () => ({ useIsMobile: () => device.mobile }));
import {
  default as ScheduleBrowser,
  ScheduleDetail,
  ExpandableText,
  schedulePurpose,
  scheduleState,
} from "./ScheduleBrowser";
vi.mock("../api/modules/cronjob", () => ({
  octopCronApi: { attempts: vi.fn(), page: vi.fn() },
}));
const empty: CronAttemptPage = {
  items: [],
  has_more: false,
  next_cursor: null,
};
const row = (id: string) =>
  ({
    id,
    name: id,
    timezone: "Asia/Shanghai",
    trigger: "interval:60",
    task_type: "text",
    prompt: "Review",
    scheduler_state: "paused",
  }) as OctopCronRow;

describe("bounded schedule browsing", () => {
  it("switches mobile detail into a single pane and returns to the task list", async () => {
    device.mobile = true;
    try {
      vi.mocked(octopCronApi.page).mockResolvedValue({
        items: [{ ...row("Mobile task"), agent_id: "main" }],
        total: 1,
        has_more: false,
        next_offset: null,
        counts: { schedules: 1, reminders: 0 },
      });
      vi.mocked(octopCronApi.attempts).mockResolvedValue(empty);
      render(
        <MemoryRouter>
          <ScheduleBrowser agentId="main" />
        </MemoryRouter>,
      );
      fireEvent.click(await screen.findByText("Mobile task"));
      const list = screen.getByRole("navigation", {
        name: "workspace0034.schedules",
        hidden: true,
      });
      expect(list.parentElement).toHaveClass(styles.mobileDetail);
      fireEvent.click(
        screen.getByRole("button", { name: "workspace0034.backToTasks" }),
      );
      expect(list.parentElement).not.toHaveClass(styles.mobileDetail);
    } finally {
      device.mobile = false;
    }
  });
  it("loads five more only on request and shows category colors", async () => {
    vi.mocked(octopCronApi.page).mockImplementation(
      async (_query, offset = 0) => ({
        items: Array.from({ length: 5 }, (_, index) => ({
          ...row(`Task ${offset + index}`),
          agent_id: "main",
          category: offset ? ("ended" as const) : ("once" as const),
        })),
        total: 10,
        has_more: offset === 0,
        next_offset: offset === 0 ? 5 : null,
        counts: { schedules: 10, reminders: 0 },
      }),
    );
    render(
      <MemoryRouter>
        <ScheduleBrowser agentId="main" />
      </MemoryRouter>,
    );
    await screen.findByText("Task 4");
    expect(screen.queryByText("Task 5")).toBeNull();
    expect(octopCronApi.page).toHaveBeenLastCalledWith(
      { agent_id: "main", reminder: false, search: "" },
      0,
      5,
    );
    expect(screen.getAllByText("workspace0034.category.once")[0]).toHaveClass(
      "ant-tag-blue",
    );
    fireEvent.click(
      screen.getByRole("button", { name: "workspace0034.moreFive" }),
    );
    await screen.findByText("Task 9");
    expect(octopCronApi.page).toHaveBeenLastCalledWith(
      { agent_id: "main", reminder: false, search: "" },
      5,
      5,
    );
    expect(screen.getByText("Task 0")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "workspace0034.moreFive" }),
    ).toBeNull();
  });

  it("discards an old expert's pending page after a scope switch", async () => {
    let finish!: (value: Awaited<ReturnType<typeof octopCronApi.page>>) => void;
    const delayed = new Promise<Awaited<ReturnType<typeof octopCronApi.page>>>(
      (yes) => {
        finish = yes;
      },
    );
    const result = (id: string) => ({
      items: [{ ...row(id), agent_id: id }],
      total: 1,
      has_more: false,
      next_offset: null,
      counts: { schedules: 1, reminders: 0 },
    });
    vi.mocked(octopCronApi.page).mockImplementation(async (query) =>
      query.agent_id === "A" ? delayed : result("B"),
    );
    const view = (id: string) => (
      <MemoryRouter>
        <ScheduleBrowser agentId={id} />
      </MemoryRouter>
    );
    const { rerender } = render(view("A"));
    rerender(view("B"));
    await screen.findByText("B");
    await act(async () => {
      finish(result("A"));
      await Promise.resolve();
    });
    expect(screen.queryByText("A")).toBeNull();
    expect(screen.getByText("B")).toBeInTheDocument();
  });
});
describe("schedule attempt selection", () => {
  it("hides the current-conversation shortcut and closes the panel before opening the execution message", async () => {
    vi.mocked(octopCronApi.attempts).mockResolvedValue({
      ...empty,
      items: [
        {
          id: 1,
          attempt_id: "attempt",
          source_thread_id: "source",
          actual_thread_id: "actual",
          run_id: "run",
          reason: "timer",
          status: "completed",
          created_at: 10,
          started_at: 11,
          finished_at: 12,
          result_excerpt: "Training finished",
          public_error: null,
        },
      ],
    });
    const close = vi.fn();
    function Probe() {
      const location = useLocation();
      return (
        <output>{location.pathname + JSON.stringify(location.state)}</output>
      );
    }
    render(
      <MemoryRouter>
        <ScheduleDetail
          agentId="main"
          item={{ ...row("A"), thread_id: "source" }}
          currentThreadId="source"
          onNavigate={close}
        />
        <Probe />
      </MemoryRouter>,
    );
    expect(
      screen.queryByRole("button", { name: "workspace0034.openConversation" }),
    ).toBeNull();
    fireEvent.click(
      await screen.findByRole("button", {
        name: "workspace0034.viewConversation",
      }),
    );
    expect(close).toHaveBeenCalledOnce();
    expect(screen.getByRole("status")).toHaveTextContent(
      '/chat/main/actual{"scheduleMessage":{"threadId":"actual","after":11000,"before":12000,"excerpt":"Training finished"}}',
    );
  });
  it.each(["success", "error"])(
    "ignores old more %s after switching selection",
    async (outcome) => {
      let resolve!: (value: CronAttemptPage) => void;
      let reject!: (reason: Error) => void;
      const delayed = new Promise<CronAttemptPage>((yes, no) => {
        resolve = yes;
        reject = no;
      });
      vi.mocked(octopCronApi.attempts).mockImplementation(
        async (_agent, id, before) => {
          if (before) return delayed;
          return id === "A"
            ? { ...empty, has_more: true, next_cursor: 50 }
            : empty;
        },
      );
      const view = (id: string) => (
        <MemoryRouter>
          <ScheduleDetail agentId="main" item={row(id)} />
        </MemoryRouter>
      );
      const { rerender } = render(view("A"));
      await act(async () => {
        await Promise.resolve();
      });
      fireEvent.click(
        screen.getByRole("button", { name: "devices.native.more" }),
      );
      rerender(view("B"));
      await act(async () => {
        await Promise.resolve();
      });
      await act(async () => {
        if (outcome === "error") reject(new Error("old-attempt-error"));
        else resolve({ ...empty, has_more: true, next_cursor: 20 });
        await Promise.resolve();
      });
      expect(screen.queryByText("old-attempt-error")).toBeNull();
      expect(
        screen.queryByRole("button", { name: "devices.native.more" }),
      ).toBeNull();
      expect(screen.getByRole("heading", { name: "B" })).toBeInTheDocument();
    },
  );
  it("keeps the current selection busy when an older request finishes", async () => {
    let finishOld!: (page: CronAttemptPage) => void;
    const old = new Promise<CronAttemptPage>((yes) => {
      finishOld = yes;
    });
    const current = new Promise<CronAttemptPage>(() => {});
    vi.mocked(octopCronApi.attempts).mockImplementation(
      async (_agent, id, before) => {
        if (before) return id === "A" ? old : current;
        return { ...empty, has_more: true, next_cursor: 50 };
      },
    );
    const view = (id: string) => (
      <MemoryRouter>
        <ScheduleDetail agentId="main" item={row(id)} />
      </MemoryRouter>
    );
    const { rerender } = render(view("A"));
    await act(async () => {
      await Promise.resolve();
    });
    fireEvent.click(
      screen.getByRole("button", { name: "devices.native.more" }),
    );
    rerender(view("B"));
    await act(async () => {
      await Promise.resolve();
    });
    const more = screen.getByRole("button", { name: "devices.native.more" });
    fireEvent.click(more);
    expect(more).toHaveClass("ant-btn-loading");
    await act(async () => {
      finishOld(empty);
      await Promise.resolve();
    });
    expect(more).toHaveClass("ant-btn-loading");
  });
});

describe("schedule purpose and honest lifecycle", () => {
  it("uses explicit reminder purpose and never extracts template text", () => {
    expect(
      schedulePurpose({
        ...row("reminder"),
        self_reminder: true,
        name: "self-check: Old name",
        prompt: "SELF_CHECK_REMINDER secret template",
        meta: { purpose: "Review the report" },
      }),
    ).toBe("Review the report");
    expect(
      schedulePurpose({
        ...row("reminder"),
        self_reminder: true,
        name: "self-check: Old name",
      }),
    ).toBe("Old name");
    expect(
      schedulePurpose({ ...row("ordinary"), name: "self-check: User title" }),
    ).toBe("self-check: User title");
  });
  it("only describes dated terminal executions as ended", () => {
    const date = Date.parse("2026-10-19T10:00:00Z") / 1000;
    const terminal = {
      ...row("date"),
      trigger: "date:2026-10-19T10:00:00Z",
      next_run_at: null,
      last_run_at: date + 10,
      last_status: "ok",
      observed_at: date + 60,
      scheduler_state: "unregistered",
    };
    expect(scheduleState(terminal)).toBe("ended");
    expect(scheduleState({ ...terminal, trigger: "cron:* * * * *" })).toBe(
      "unregistered",
    );
    expect(scheduleState({ ...terminal, last_status: "error" })).toBe(
      "last_failed",
    );
    expect(
      scheduleState({ ...terminal, scheduler_state: "scheduler_stopped" }),
    ).toBe("scheduler_stopped");
    expect(
      scheduleState({
        ...terminal,
        scheduler_state: "scheduler_stopped",
        last_status: "error",
      }),
    ).toBe("scheduler_stopped");
    expect(scheduleState({ ...terminal, last_run_at: date - 1 })).toBe(
      "unregistered",
    );
    expect(scheduleState({ ...terminal, last_run_at: date + 61 })).toBe(
      "unregistered",
    );
    expect(scheduleState({ ...terminal, last_status: null })).toBe(
      "unregistered",
    );
    expect(scheduleState({ ...terminal, observed_at: 1 })).toBe("unregistered");
    expect(scheduleState({ ...terminal, trigger: "date:invalid" })).toBe(
      "unregistered",
    );
    expect(
      scheduleState({
        ...terminal,
        self_reminder: true,
        scheduler_state: "exhausted",
      }),
    ).toBe("exhausted");
  });

  it("defaults to execution records and hides reminder instructions until expanded", async () => {
    vi.mocked(octopCronApi.attempts).mockResolvedValue(empty);
    render(
      <MemoryRouter>
        <ScheduleDetail
          agentId="main"
          item={{
            ...row("reminder"),
            self_reminder: true,
            meta: { purpose: "Check progress" },
            prompt: "SELF_CHECK_REMINDER full template",
          }}
        />
      </MemoryRouter>,
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(
      screen.getByRole("tab", { name: "workspace0034.executionRecords" }),
    ).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByText("SELF_CHECK_REMINDER full template")).toBeNull();
    fireEvent.click(
      screen.getByRole("tab", { name: "workspace0034.scheduleContent" }),
    );
    expect(screen.getByRole("tabpanel")).toHaveAttribute(
      "aria-labelledby",
      screen.getByRole("tab", { name: "workspace0034.scheduleContent" }).id,
    );
    expect(
      screen.getByText("workspace0034.fullInstruction"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("SELF_CHECK_REMINDER full template").closest("details"),
    ).not.toHaveAttribute("open");
  });
});

describe("measured text expansion", () => {
  it("only offers expansion for actual clamped overflow and remeasures text changes", () => {
    const full = vi
      .spyOn(HTMLElement.prototype, "scrollHeight", "get")
      .mockImplementation(function (this: HTMLElement) {
        return this.textContent === "Long output" ? 120 : 24;
      });
    const visible = vi
      .spyOn(HTMLElement.prototype, "clientHeight", "get")
      .mockReturnValue(48);
    const { rerender } = render(
      <ExpandableText key="short" text="Short output" clampClass="clamped" />,
    );
    expect(
      screen.queryByRole("button", { name: "workspace0034.expand" }),
    ).toBeNull();
    rerender(
      <ExpandableText key="long" text="Long output" clampClass="clamped" />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "workspace0034.expand" }),
    );
    expect(screen.getByText("Long output")).not.toHaveClass("clamped");
    fireEvent.click(
      screen.getByRole("button", { name: "workspace0034.collapse" }),
    );
    expect(screen.getByText("Long output")).toHaveClass("clamped");
    rerender(
      <ExpandableText
        key="short-again"
        text="Short output"
        clampClass="clamped"
      />,
    );
    expect(
      screen.queryByRole("button", { name: "workspace0034.expand" }),
    ).toBeNull();
    full.mockRestore();
    visible.mockRestore();
  });
});
