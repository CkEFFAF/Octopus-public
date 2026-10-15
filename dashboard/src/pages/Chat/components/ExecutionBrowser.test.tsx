import { forwardRef, useImperativeHandle } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { executionApi } from "../../../api/modules/execution";
import ExecutionBrowser from "./ExecutionBrowser";

vi.mock("../../../api/modules/execution", () => ({
  executionApi: { call: vi.fn() },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../../../components/BrowserViewer", () => ({
  default: forwardRef(function Viewer(
    props: {
      sendEvent: (value: Record<string, unknown>) => boolean;
      onReconnect: () => void;
      interactive: boolean;
    },
    ref,
  ) {
    useImperativeHandle(ref, () => ({ paintFrame: vi.fn() }));
    return (
      <>
        <button
          onClick={() => {
            props.sendEvent({
              type: "mousedown",
              x: 10,
              y: 10,
              button: "left",
            });
            props.sendEvent({ type: "mouseup", x: 10, y: 10, button: "left" });
          }}
        >
          Click page
        </button>
        <button onClick={props.onReconnect}>Reconnect page</button>
        <span>{props.interactive ? "Input ready" : "Input stopped"}</span>
      </>
    );
  }),
}));

const context = {
  context_id: "original-device",
  device_id: "gpu",
  working_dir: "/work",
  work_mode: "agentic" as const,
  policy_revision: 1,
  grant_version: 1,
};
const state = {
  session_id: "browser",
  tabs: [
    {
      id: "tab",
      active: true,
      title: "Local page",
      url: "http://localhost:3000",
    },
  ],
};
beforeEach(() => vi.clearAllMocks());

it("stops queued browser input after a lost receipt and only resumes on explicit reconnect", async () => {
  let fails = true;
  vi.mocked(executionApi.call).mockImplementation(
    async (_context, action, params) => {
      if (action === "browser.capture") return new Promise(() => undefined);
      if (
        action === "browser.action" &&
        params.command !== "reset_input" &&
        fails
      )
        throw new Error("receipt unavailable");
      return state;
    },
  );
  const user = userEvent.setup();
  render(<ExecutionBrowser context={context} visible />);
  await screen.findByText("Input ready");
  await user.click(screen.getByRole("button", { name: "Click page" }));
  await screen.findByText("chat.execution.browserInputUnknown");
  const inputs = () =>
    vi
      .mocked(executionApi.call)
      .mock.calls.filter((call) => call[1] === "browser.action");
  expect(inputs()).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "Click page" }));
  expect(inputs()).toHaveLength(1);
  fails = false;
  await user.click(screen.getByRole("button", { name: "Reconnect page" }));
  await screen.findByText("Input ready");
  expect(inputs()).toHaveLength(2);
  expect(inputs()[1]).toEqual([
    "original-device",
    "browser.action",
    { command: "reset_input" },
  ]);
  await user.click(screen.getByRole("button", { name: "Click page" }));
  await waitFor(() => expect(inputs()).toHaveLength(4));
  expect(inputs().every((call) => call[0] === "original-device")).toBe(true);
});

it("pauses capture when its dock tab is hidden", async () => {
  vi.mocked(executionApi.call).mockImplementation(async (_context, action) => {
    if (action === "browser.capture") return new Promise(() => undefined);
    return state;
  });
  const { rerender } = render(
    <ExecutionBrowser context={context} visible={false} />,
  );
  await waitFor(() =>
    expect(executionApi.call).toHaveBeenCalledWith(
      "original-device",
      "browser.open",
      {},
    ),
  );
  expect(
    vi
      .mocked(executionApi.call)
      .mock.calls.filter((call) => call[1] === "browser.capture"),
  ).toHaveLength(0);
  rerender(<ExecutionBrowser context={context} visible />);
  await waitFor(() =>
    expect(
      vi
        .mocked(executionApi.call)
        .mock.calls.filter((call) => call[1] === "browser.capture"),
    ).toHaveLength(1),
  );
});
