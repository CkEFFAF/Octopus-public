import { describe, expect, it } from "vitest";
import type { OctopCronRow } from "../../../api/types";
import { fromOctop, jobToFormValues, toOctopCreateBody } from "./useCronJobs";

describe("scheduled report settings", () => {
  it("retains both independent settings and the history count when editing", () => {
    const row: OctopCronRow = {
      id: "daily",
      name: "Daily",
      agent_id: "agent",
      trigger: "cron:0 9 * * *",
      prompt: "Report",
      session_key: "agent:dashboard:1:report-daily",
      fresh_thread: true,
      enabled: true,
      task_type: "agent",
      model: null,
      last_run_at: null,
      last_status: null,
      last_error: null,
      kind: "daily_report",
      report_options: {
        new_conversation: true,
        include_previous: true,
        previous_count: 7,
      },
    };
    const values = jobToFormValues(
      fromOctop(row, "Asia/Shanghai"),
      "Asia/Shanghai",
    );
    expect(values.task_type).toBe("daily_report");
    expect(values.report_new_conversation).toBe(true);
    expect(values.report_include_previous).toBe(true);
    expect(values.report_previous_count).toBe(7);
    expect(toOctopCreateBody(values)).toMatchObject({
      task_type: "agent",
      session_key: null,
      report_options: {
        new_conversation: true,
        include_previous: true,
        previous_count: 7,
      },
    });
  });

  it("does not enable report behavior for ordinary tasks", () => {
    const row: OctopCronRow = {
      id: "ordinary",
      name: "Ordinary",
      agent_id: "agent",
      trigger: "interval:60",
      prompt: "Reminder",
      session_key: "agent:dashboard:1:dm",
      fresh_thread: false,
      enabled: true,
      task_type: "agent",
      model: null,
      last_run_at: null,
      last_status: null,
      last_error: null,
    };
    const values = jobToFormValues(fromOctop(row, "UTC"), "UTC");
    expect(values.task_type).toBe("agent");
    expect(toOctopCreateBody(values).report_options).toBeNull();
  });
});
