import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { octopCronApi, type CronAttemptPage } from "../api/modules/cronjob";
import type { OctopCronRow } from "../api/types";
import {
  ScheduleDetail,
  ExpandableText,
  schedulePurpose,
  scheduleState,
} from "./ScheduleBrowser";
vi.mock("../api/modules/cronjob", () => ({
  octopCronApi: { attempts: vi.fn() },
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
describe("schedule attempt selection", () => {
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
