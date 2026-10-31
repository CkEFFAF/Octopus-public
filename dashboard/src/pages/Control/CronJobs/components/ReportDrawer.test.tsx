import { Form } from "antd";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { CronJobFormValues } from "../useCronJobs";
import { JobDrawer } from "./JobDrawer";

vi.mock("../../../../api/modules/provider", () => ({
  providerApi: { listResolvedModels: vi.fn().mockResolvedValue([]) },
}));
vi.mock("../../../../api/modules/connectors", () => ({
  connectorsApi: { listInstances: vi.fn().mockResolvedValue([]) },
}));
vi.mock("../../../../api/modules/octopThreads", () => ({
  octopThreadsApi: { list: vi.fn().mockResolvedValue([]) },
}));

function ReportForm() {
  const [form] = Form.useForm<CronJobFormValues>();
  return (
    <JobDrawer
      open
      activeAgentId="agent"
      cronTimezone="UTC"
      form={form}
      editingJob={{
        id: "daily",
        name: "Daily",
        enabled: true,
        schedule: { type: "cron", cron: "0 9 * * *", timezone: "UTC" },
        prompt: "Report",
        task_type: "daily_report",
        fresh_thread: false,
        report_new_conversation: false,
        report_include_previous: false,
        report_previous_count: 1,
      }}
      onClose={() => {}}
      onSubmit={() => {}}
    />
  );
}

describe("daily report editor", () => {
  it("shows independent conversation and history controls", async () => {
    render(<ReportForm />);
    const conversation = await screen.findByLabelText(
      "cronJobs.form.reportNewConversation",
    );
    const previous = screen.getByLabelText(
      "cronJobs.form.reportIncludePrevious",
    );
    expect(conversation).not.toBeChecked();
    expect(previous).not.toBeChecked();
    expect(
      screen.queryByLabelText("cronJobs.form.reportPreviousCount"),
    ).toBeNull();
    fireEvent.click(conversation);
    expect(conversation).toBeChecked();
    expect(previous).not.toBeChecked();
    fireEvent.click(previous);
    expect(
      screen.getByLabelText("cronJobs.form.reportPreviousCount"),
    ).toBeVisible();
    expect(conversation).toBeChecked();
  });
});
