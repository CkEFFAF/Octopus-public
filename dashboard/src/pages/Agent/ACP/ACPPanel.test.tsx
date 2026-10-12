import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ACPRunnerConfig } from "../../../api/types/acp";

const { getGlobalRunners, updateGlobalRunners, translate } = vi.hoisted(() => ({
  getGlobalRunners: vi.fn(),
  updateGlobalRunners: vi.fn(),
  translate: (key: string) => key,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: translate }),
}));
vi.mock("../../../api/modules/acp", () => ({
  acpApi: { getGlobalRunners, updateGlobalRunners },
}));
vi.mock("../../../context/AgentContext", () => ({
  useAgent: () => ({ activeAgentId: null, agents: [] }),
}));
vi.mock("../../../components/PeerOnlyRemoteAlert", () => ({
  default: () => null,
}));

import { ACPPanel } from "./index";

const presets: Record<string, ACPRunnerConfig> = Object.fromEntries(
  [
    ["hermes", "hermes", ["acp"]],
    ["grok_build", "grok", ["agent", "stdio"]],
    ["openclaw", "openclaw", ["acp"]],
  ].map(([key, command, args]) => [
    key,
    {
      enabled: false,
      command,
      args,
      env: {},
      trusted: true,
      tool_parse_mode: "update_detail",
      stdio_buffer_limit_bytes: 52428800,
    },
  ]),
);

function show() {
  return render(
    <App>
      <ACPPanel />
    </App>,
  );
}

describe("extended ACP presets", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getGlobalRunners.mockResolvedValue({ runners: presets });
    updateGlobalRunners.mockImplementation(async (runners) => ({ runners }));
  });

  it("renders disabled presets and enables the selected runner only", async () => {
    show();
    const label = await screen.findByText("acp.runner_hermes");
    expect(screen.getByText("acp.runner_grok_build")).toBeInTheDocument();
    expect(screen.getByText("acp.runner_openclaw")).toBeInTheDocument();
    const toggle = within(label.parentElement!).getByRole("switch");
    expect(toggle).not.toBeChecked();
    fireEvent.click(toggle);
    await waitFor(() =>
      expect(updateGlobalRunners).toHaveBeenCalledWith(
        {
          ...presets,
          hermes: { ...presets.hermes, enabled: true },
        },
        undefined,
      ),
    );
    await waitFor(() => expect(toggle).toBeChecked());
  });

  it.each([
    ["hermes", "hermes"],
    ["grok_build", "grok"],
    ["openclaw", "openclaw"],
  ])(
    "edits %s without allowing its built-in identity to be deleted",
    async (key, command) => {
      show();
      fireEvent.click(await screen.findByText(`acp.runner_${key}`));
      const field = await screen.findByRole("textbox", { name: "acp.command" });
      await waitFor(() => expect(field).toHaveValue(command));
      expect(
        screen.getByRole("textbox", { name: "acp.runnerKey" }),
      ).toBeDisabled();
      expect(
        screen.queryByRole("button", { name: "common.delete" }),
      ).not.toBeInTheDocument();
      fireEvent.change(field, { target: { value: "my-runner" } });
      fireEvent.click(screen.getByRole("button", { name: "common.save" }));
      await waitFor(() =>
        expect(updateGlobalRunners).toHaveBeenCalledWith(
          {
            ...presets,
            [key]: { ...presets[key], command: "my-runner" },
          },
          undefined,
        ),
      );
    },
  );
});
