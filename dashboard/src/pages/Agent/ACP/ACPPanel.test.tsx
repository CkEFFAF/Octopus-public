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

const {
  getGlobalRunners,
  updateGlobalRunners,
  getDeviceRunners,
  updateDeviceRunner,
  resetDeviceRunner,
  checkDeviceRunner,
  translate,
} = vi.hoisted(() => ({
  getGlobalRunners: vi.fn(),
  updateGlobalRunners: vi.fn(),
  getDeviceRunners: vi.fn(),
  updateDeviceRunner: vi.fn(),
  resetDeviceRunner: vi.fn(),
  checkDeviceRunner: vi.fn(),
  translate: (key: string) => key,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: translate }),
}));
vi.mock("../../../api/modules/acp", () => ({
  acpApi: {
    getGlobalRunners,
    updateGlobalRunners,
    getDeviceRunners,
    updateDeviceRunner,
    resetDeviceRunner,
    checkDeviceRunner,
  },
}));
vi.mock("../../../api/modules/devices", () => ({
  devicesApi: {
    list: async () => ({ devices: [{ device_id: "laptop", name: "Laptop" }] }),
  },
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
    window.history.replaceState({}, "", "/acp");
    getDeviceRunners.mockResolvedValue({ runners: presets, overrides: [] });
    updateDeviceRunner.mockResolvedValue({ runners: presets });
    resetDeviceRunner.mockResolvedValue({ runners: presets });
    checkDeviceRunner.mockResolvedValue({
      available: true,
      executable: "device-bin",
    });
    getGlobalRunners.mockResolvedValue({ runners: presets });
    updateGlobalRunners.mockImplementation(async (runners) => ({ runners }));
  });

  it("saves an override on the selected device without changing account templates", async () => {
    window.history.replaceState({}, "", "/acp?device=laptop");
    show();
    const label = await screen.findByText("acp.runner_hermes");
    fireEvent.click(within(label.parentElement!).getByRole("switch"));
    await waitFor(() =>
      expect(updateDeviceRunner).toHaveBeenCalledWith("laptop", "hermes", {
        ...presets.hermes,
        enabled: true,
      }),
    );
    expect(updateGlobalRunners).not.toHaveBeenCalled();
    expect(getGlobalRunners).not.toHaveBeenCalled();
  });

  it("checks and resets saved device settings while keeping credentials off the form", async () => {
    window.history.replaceState({}, "", "/acp?device=laptop");
    show();
    fireEvent.click(await screen.findByText("acp.runner_hermes"));
    expect(
      screen.queryByRole("textbox", { name: "acp.env" }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      await screen.findByRole("button", { name: "acp.checkSaved" }),
    );
    await waitFor(() =>
      expect(checkDeviceRunner).toHaveBeenCalledWith("laptop", "hermes"),
    );
    fireEvent.click(screen.getByRole("button", { name: "acp.resetDevice" }));
    await waitFor(() =>
      expect(resetDeviceRunner).toHaveBeenCalledWith("laptop", "hermes"),
    );
    expect(updateGlobalRunners).not.toHaveBeenCalled();
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
