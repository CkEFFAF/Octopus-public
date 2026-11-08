import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  MODEL_TASKS,
  modelRoutingApi,
  type ModelRoutingView,
} from "../../../api/modules/modelRouting";
import ModelRoutingPanel from "./ModelRoutingPanel";

vi.mock("../../../api/modules/modelRouting", async (original) => ({
  ...(await original<typeof import("../../../api/modules/modelRouting")>()),
  modelRoutingApi: { get: vi.fn(), save: vi.fn(), preview: vi.fn() },
}));
const view: ModelRoutingView = {
  enabled: false,
  tasks: {},
  models: [],
  resolved: Object.fromEntries(
    MODEL_TASKS.map((task) => [
      task,
      {
        task,
        model: "Owner/DeepSeek",
        source: "default",
        reason: "routing_disabled",
        available: true,
      },
    ]),
  ) as ModelRoutingView["resolved"],
  auxiliary_overrides: {},
  memory_apply: "next_expert_reload",
};
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(modelRoutingApi.get).mockResolvedValue(view);
  vi.mocked(modelRoutingApi.save).mockImplementation(async (draft) => ({
    ...view,
    ...draft,
  }));
  vi.mocked(modelRoutingApi.preview).mockResolvedValue({
    ...view.resolved.chat,
    task: "coding",
    source: "task",
    reason: "task_model",
  });
});
it("keeps unsaved choices on a failed save and retries the same draft", async () => {
  vi.mocked(modelRoutingApi.save).mockRejectedValueOnce(
    new Error("Save unavailable"),
  );
  render(<ModelRoutingPanel />);
  const toggle = await screen.findByRole("switch", {
    name: "modelRouting.enable",
  });
  await waitFor(() => expect(toggle).toBeEnabled());
  fireEvent.click(toggle);
  expect(
    screen.getByRole("button", { name: "modelRouting.saveFirst" }),
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "common.save" }));
  expect(
    await screen.findByText("Error: Save unavailable"),
  ).toBeInTheDocument();
  expect(toggle).toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "common.save" }));
  await waitFor(() => expect(modelRoutingApi.save).toHaveBeenCalledTimes(2));
  expect(vi.mocked(modelRoutingApi.save).mock.calls[1][0]).toEqual({
    enabled: true,
    tasks: {},
  });
  expect(await screen.findByText("modelRouting.saved")).toBeInTheDocument();
});
it("previews saved routing without saving settings or making a model call", async () => {
  render(<ModelRoutingPanel />);
  const input = await screen.findByRole("textbox", {
    name: "modelRouting.previewInput",
  });
  fireEvent.change(input, { target: { value: "修复 Python 报错" } });
  fireEvent.click(screen.getByRole("button", { name: "modelRouting.preview" }));
  await waitFor(() =>
    expect(modelRoutingApi.preview).toHaveBeenCalledWith({
      text: "修复 Python 报错",
      task: undefined,
      has_images: false,
      context_tokens: 0,
    }),
  );
  expect(modelRoutingApi.save).not.toHaveBeenCalled();
  expect(await screen.findByText("modelRouting.decision")).toBeInTheDocument();
});
it("refreshes availability without discarding unsaved preferences", async () => {
  render(<ModelRoutingPanel />);
  const toggle = await screen.findByRole("switch", {
    name: "modelRouting.enable",
  });
  await waitFor(() => expect(toggle).toBeEnabled());
  fireEvent.click(toggle);
  fireEvent.click(screen.getByRole("button", { name: "modelRouting.refresh" }));
  await waitFor(() => expect(modelRoutingApi.get).toHaveBeenCalledTimes(2));
  expect(toggle).toBeChecked();
  expect(screen.getByRole("button", { name: "common.save" })).toBeEnabled();
});
