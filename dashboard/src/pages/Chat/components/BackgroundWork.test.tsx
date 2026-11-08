import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import {
  workItemsApi,
  type WorkItemDetail,
} from "../../../api/modules/workItems";
import {
  executionScope,
  setExecutionSelection,
  setExecutionSelectionStatus,
} from "../hooks/deviceTarget";
import BackgroundWork from "./BackgroundWork";

vi.mock("../../../api/modules/workItems", () => ({
  workItemsApi: {
    list: vi.fn(),
    detail: vi.fn(),
    create: vi.fn(),
    input: vi.fn(),
    cancel: vi.fn(),
  },
}));
vi.mock("../../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "Asia/Shanghai",
}));
const detail: WorkItemDetail = {
  task_id: "task-a",
  title: "Render report",
  status: "running",
  cancel_requested: false,
  origin_thread_id: "origin",
  agent_id: "agent",
  instructions: "Long-running independent job",
  origin_thread_missing: false,
  current_run_id: "run-a",
  current_attempt_id: "attempt-a",
  updated_at: 1794028800,
  progress: {
    phase: "running",
    active_tools: ["shell"],
    last_event_at: 1794028800,
    block_reason: null,
    needs_approval: false,
    needs_credential: false,
    permission_denied: false,
  },
};
const scope = executionScope("agent", "origin");
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(workItemsApi.list).mockResolvedValue({
    items: [detail],
    has_more: false,
  });
  vi.mocked(workItemsApi.detail).mockResolvedValue(detail);
  setExecutionSelection(scope, {
    deviceId: "laptop",
    workMode: "agentic",
    workingDir: "D:/project",
  });
  setExecutionSelectionStatus(scope, "ready");
});
function host() {
  return render(
    <MemoryRouter>
      <BackgroundWork agentId="agent" threadId="origin" />
    </MemoryRouter>,
  );
}
async function openTask() {
  fireEvent.click(
    await screen.findByRole("button", { name: /chat.workItems.title/ }),
  );
  fireEvent.click(await screen.findByText(detail.title));
  await screen.findByText(detail.instructions);
}
it("reads task progress without sending messages, creating tasks, or cancelling", async () => {
  host();
  await openTask();
  expect(workItemsApi.detail).toHaveBeenCalledWith("task-a");
  expect(workItemsApi.create).not.toHaveBeenCalled();
  expect(workItemsApi.input).not.toHaveBeenCalled();
  expect(workItemsApi.cancel).not.toHaveBeenCalled();
  expect(screen.getByText("shell")).toBeInTheDocument();
});
it("shows cancellation intent until the server confirms termination", async () => {
  host();
  await openTask();
  vi.mocked(workItemsApi.cancel).mockResolvedValue({
    cancel_requested: true,
    status: "running",
    terminated: false,
  });
  vi.mocked(workItemsApi.detail).mockResolvedValue({
    ...detail,
    cancel_requested: true,
  });
  fireEvent.click(
    screen.getByRole("button", { name: "chat.workItems.cancel" }),
  );
  await waitFor(() =>
    expect(workItemsApi.cancel).toHaveBeenCalledWith(
      "task-a",
      expect.any(String),
    ),
  );
  expect(
    await screen.findByRole("button", {
      name: "chat.workItems.status.cancelling",
    }),
  ).toBeDisabled();
  expect(
    screen.queryByText("chat.workItems.status.cancelled"),
  ).not.toBeInTheDocument();
});
it("sends explicit requirements to only the selected worker attempt", async () => {
  vi.mocked(workItemsApi.input).mockResolvedValue({});
  host();
  await openTask();
  fireEvent.change(screen.getByLabelText("chat.workItems.addRequirements"), {
    target: { value: "Export as PDF" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "chat.workItems.sendRequirements" }),
  );
  await waitFor(() =>
    expect(workItemsApi.input).toHaveBeenCalledWith(
      detail,
      "Export as PDF",
      expect.any(String),
    ),
  );
  expect(workItemsApi.cancel).not.toHaveBeenCalled();
});
it("retains the command id when retrying an unconfirmed create request", async () => {
  vi.mocked(workItemsApi.create).mockRejectedValueOnce(new Error("network"));
  host();
  fireEvent.click(screen.getByRole("button", { name: /chat.workItems.title/ }));
  fireEvent.click(screen.getByRole("button", { name: "chat.workItems.new" }));
  fireEvent.change(screen.getByLabelText("chat.workItems.taskTitle"), {
    target: { value: "New task" },
  });
  fireEvent.change(screen.getByLabelText("chat.workItems.instructions"), {
    target: { value: "Create a report" },
  });
  fireEvent.click(screen.getByRole("button", { name: "chat.workItems.start" }));
  await waitFor(() => expect(workItemsApi.create).toHaveBeenCalledTimes(1));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "chat.workItems.start" }),
    ).toBeEnabled(),
  );
  vi.mocked(workItemsApi.create).mockResolvedValue({ task_id: "task-a" });
  fireEvent.click(screen.getByRole("button", { name: "chat.workItems.start" }));
  await waitFor(() => expect(workItemsApi.create).toHaveBeenCalledTimes(2));
  expect(vi.mocked(workItemsApi.create).mock.calls[0][1]).toBe(
    vi.mocked(workItemsApi.create).mock.calls[1][1],
  );
  expect(vi.mocked(workItemsApi.create).mock.calls[0][0]).toMatchObject({
    origin_thread_id: "origin",
    execution: {
      target_kind: "device",
      device_id: "laptop",
      working_dir: "D:/project",
    },
  });
});
it("does not upgrade an Ask-mode selection into background execution", async () => {
  setExecutionSelection(scope, { workMode: "ask" });
  host();
  fireEvent.click(screen.getByRole("button", { name: /chat.workItems.title/ }));
  fireEvent.click(screen.getByRole("button", { name: "chat.workItems.new" }));
  expect(
    screen.getByRole("button", { name: "chat.workItems.start" }),
  ).toBeDisabled();
  expect(workItemsApi.create).not.toHaveBeenCalled();
});
