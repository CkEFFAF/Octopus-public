import { useState } from "react";
import { App } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import History from "./OrganizationHistory";
import {
  conversationMetadataApi as api,
  type OrganizationAge,
  type OrganizationStatus,
} from "../../../api/modules/conversationMetadata";

vi.mock("../../../api/modules/conversationMetadata", () => ({
  conversationMetadataApi: { organizationPage: vi.fn(), generate: vi.fn() },
}));
const row = {
  thread_id: "failed-conversation",
  agent_id: "expert",
  agent_name: "研究专家",
  title: "迁移实验结果分析",
  status: "failed",
  last_success_at: 1700000000,
  last_attempt_at: 1700600000,
  error_code: "METADATA_INVALID_OUTPUT",
  diagnostic: {
    issues: [{ path: "remaining.0.source_refs", type: "missing" }],
  },
  job_id: "failed-job",
};

function Harness() {
  const [age, setAge] = useState<OrganizationAge>("all");
  const [status, setStatus] = useState<OrganizationStatus>("failed");
  return (
    <App>
      <History
        age={age}
        status={status}
        pending={false}
        onFilter={(a, s) => {
          setAge(a);
          setStatus(s);
        }}
      />
    </App>
  );
}
it("identifies a failed conversation, retains its successful timestamp and retries it", async () => {
  vi.mocked(api.organizationPage).mockResolvedValue({
    items: [row],
    total: 1,
    offset: 0,
    limit: 20,
  });
  vi.mocked(api.generate).mockImplementation(async () => {
    vi.mocked(api.organizationPage).mockResolvedValue({
      items: [{ ...row, status: "queued" }],
      total: 1,
      offset: 0,
      limit: 20,
    });
    return {
      job_id: "retry-job",
      kind: "brief",
      status: "queued",
      attempts: 0,
      error_code: "",
      result: {},
      updated_at: 1700600001,
    };
  });
  render(<Harness />);
  expect(await screen.findByText("迁移实验结果分析")).toBeVisible();
  expect(screen.getByText("研究专家")).toBeVisible();
  expect(
    screen.getByText("conversationMetadata.generationFailed"),
  ).toBeVisible();
  expect(screen.queryByText(/remaining.0.source_refs/)).toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "common.failureDetails" }),
  );
  await waitFor(() =>
    expect(screen.getByText(/remaining.0.source_refs/)).toBeVisible(),
  );
  fireEvent.click(screen.getByRole("button", { name: "common.close" }));
  fireEvent.click(
    screen.getByRole("button", { name: "organizationHistory.retry" }),
  );
  await waitFor(() =>
    expect(api.generate).toHaveBeenCalledWith(
      "expert",
      "failed-conversation",
      "brief",
    ),
  );
  expect(
    await screen.findByText("organizationHistory.status.active"),
  ).toBeVisible();
});

it("sends age and status filters to the server before pagination", async () => {
  vi.mocked(api.organizationPage).mockResolvedValue({
    items: [],
    total: 0,
    offset: 0,
    limit: 20,
  });
  render(<Harness />);
  await screen.findByText("organizationHistory.empty");
  fireEvent.mouseDown(
    screen.getByRole("combobox", { name: "organizationHistory.ageFilter" }),
  );
  fireEvent.click(await screen.findByText("organizationHistory.ages.d3"));
  await waitFor(() =>
    expect(api.organizationPage).toHaveBeenCalledWith(
      "d3",
      "failed",
      0,
      undefined,
    ),
  );
});

it("returns from an emptied failure page after successful retries reduce the total", async () => {
  let shrunk = false;
  vi.mocked(api.organizationPage).mockImplementation(
    async (_age, _status, offset = 0) => ({
      items:
        offset === 20
          ? shrunk
            ? []
            : [{ ...row, thread_id: "last", title: "Last failed conversation" }]
          : Array.from({ length: 20 }, (_, i) => ({
              ...row,
              thread_id: `page-${i}`,
              title: `Failed conversation ${i}`,
            })),
      total: shrunk ? 20 : 21,
      offset,
      limit: 20,
    }),
  );
  render(<Harness />);
  await screen.findByText("Failed conversation 0");
  fireEvent.click(screen.getByTitle("2"));
  await screen.findByText("Last failed conversation");
  shrunk = true;
  fireEvent.click(screen.getByRole("button", { name: "common.refresh" }));
  expect(await screen.findByText("Failed conversation 0")).toBeVisible();
  expect(vi.mocked(api.organizationPage).mock.lastCall?.[2]).toBe(0);
});
