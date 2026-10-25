import { useEffect, useRef } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { executionApi } from "../../../api/modules/execution";
import ExecutionTerminal from "./ExecutionTerminal";

vi.mock("../../../api/modules/execution", () => ({
  executionApi: { call: vi.fn() },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../../Control/Terminal/components/TerminalView", () => ({
  default: function View({
    onReady,
    onData,
  }: {
    onReady: () => void;
    onData: (value: string) => void;
  }) {
    const readyAtMount = useRef(onReady);
    useEffect(() => {
      readyAtMount.current();
    }, []);
    return (
      <button onClick={() => onData("a".repeat(2500) + "\r")}>
        Paste command
      </button>
    );
  },
}));

it("stops queued paste chunks after an unconfirmed input instead of sending a partial command", async () => {
  vi.mocked(executionApi.call).mockImplementation(async (_context, action) => {
    if (action === "terminal.poll") return new Promise(() => undefined);
    if (action === "terminal.input") throw new Error("receipt unavailable");
    return {};
  });
  const user = userEvent.setup();
  render(
    <ExecutionTerminal
      visible
      context={{
        context_id: "original-context",
        device_id: "device",
        working_dir: "/work",
        policy_revision: 1,
        grant_version: 1,
        work_mode: "agentic",
      }}
    />,
  );
  await waitFor(() =>
    expect(executionApi.call).toHaveBeenCalledWith(
      "original-context",
      "terminal.poll",
      expect.anything(),
    ),
  );
  await user.click(screen.getByRole("button", { name: "Paste command" }));
  expect(
    await screen.findByText("chat.execution.inputUnknown"),
  ).toBeInTheDocument();
  expect(
    vi
      .mocked(executionApi.call)
      .mock.calls.filter((call) => call[1] === "terminal.input"),
  ).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "Paste command" }));
  expect(
    vi
      .mocked(executionApi.call)
      .mock.calls.filter((call) => call[1] === "terminal.input"),
  ).toHaveLength(1);
});
