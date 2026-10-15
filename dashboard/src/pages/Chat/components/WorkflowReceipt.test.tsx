import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { executionApi, type RunEvent } from "../../../api/modules/execution";
import WorkflowReceipt from "./WorkflowReceipt";

vi.mock("../../../api/modules/execution", () => ({
  executionApi: { decide: vi.fn() },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const event: RunEvent = {
  seq: 1,
  event_id: "workflow:expert:thread:run",
  run_id: "run",
  agent_id: "expert",
  thread_id: "thread",
  kind: "workflow",
  status: "needs_input",
  created_at: 1,
  updated_at: 1,
  context_id: null,
  payload: {
    mode: "cowork",
    version: 3,
    stages: [
      { name: "work", status: "completed" },
      {
        name: "handoff",
        status: "needs_input",
        report: "A decision is needed",
        decision: {
          question: "Which route?",
          options: ["Route A", "Route B"],
          recommendation: 0,
        },
      },
    ],
  },
};

beforeEach(() => vi.clearAllMocks());

it("submits the user's explicit choice with the frozen workflow version", async () => {
  vi.mocked(executionApi.decide).mockResolvedValue({
    ...event,
    status: "completed",
  });
  const changed = vi.fn();
  render(
    <WorkflowReceipt
      event={event}
      agentId="expert"
      threadId="thread"
      onChanged={changed}
    />,
  );
  expect(executionApi.decide).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Route B" }));
  await waitFor(() => expect(changed).toHaveBeenCalledOnce());
  expect(executionApi.decide).toHaveBeenCalledWith(
    "expert",
    "thread",
    event.event_id,
    3,
    1,
  );
});

it("retains the decision and shows a conflict instead of claiming it was accepted", async () => {
  vi.mocked(executionApi.decide).mockRejectedValue(
    new Error("handoff changed"),
  );
  const changed = vi.fn();
  render(
    <WorkflowReceipt
      event={event}
      agentId="expert"
      threadId="thread"
      onChanged={changed}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Route B" }));
  expect(await screen.findByText("handoff changed")).toBeInTheDocument();
  expect(changed).not.toHaveBeenCalled();
});
