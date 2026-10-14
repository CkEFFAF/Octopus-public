import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Device } from "../../api/modules/devices";

const { list, operations, update, call, switchDesktopTarget, user } =
  vi.hoisted(() => ({
    list: vi.fn(),
    operations: vi.fn(),
    update: vi.fn(),
    call: vi.fn(),
    switchDesktopTarget: vi.fn(),
    user: { role: "user", permissions: ["terminal"] },
  }));
vi.mock("../../api/modules/devices", () => ({
  devicesApi: { list, operations, update, call, switchDesktopTarget },
}));
vi.mock("../../api/config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
}));
vi.mock("../../hooks/useCurrentUser", () => ({ useCurrentUser: () => user }));
vi.mock("../../hooks/useServerCapabilities", () => ({
  useServerCapabilities: () => ({ mobileEnabled: false }),
}));
vi.mock("../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "Asia/Shanghai",
}));
vi.mock("../../layouts/PageShell", () => ({
  default: ({
    title,
    actions,
    children,
  }: {
    title: string;
    actions: React.ReactNode;
    children: React.ReactNode;
  }) => (
    <main>
      <h1>{title}</h1>
      {actions}
      {children}
    </main>
  ),
}));
vi.mock("./AccessKeys", () => ({ default: () => null }));
vi.mock("../../components/AvatarDropdown", () => ({ default: () => null }));
vi.mock("./DeviceDesktop", () => ({
  default: ({ device }: { device: Device }) => (
    <div data-testid="remote-desktop">{device.device_id}</div>
  ),
}));
vi.mock("./DeviceFiles", () => ({
  default: ({ device }: { device: Device }) => (
    <div data-testid="remote-files">{device.device_id}</div>
  ),
}));

import DevicesPage from "./index";
import WorkspaceNav from "../../layouts/WorkspaceNav";

const windows: Device = {
  device_id: "windows-office",
  name: "Office Windows",
  platform: "windows",
  permissions: ["desktop_view", "files_read"],
  capabilities: ["desktop_view", "files_read"],
  roots: [],
  online: true,
  grant_version: 1,
  last_seen_at: null,
  revoked_at: null,
};
const linux: Device = {
  ...windows,
  device_id: "linux-headless",
  name: "Headless Linux",
  platform: "linux",
  permissions: ["files_read", "command_exec"],
  capabilities: ["files_read", "command_exec"],
};

function Location() {
  const location = useLocation();
  return (
    <output data-testid="location">
      {location.pathname}
      {location.search}
    </output>
  );
}
function show(path = "/devices") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App>
        <DevicesPage />
        <Location />
      </App>
    </MemoryRouter>,
  );
}

describe("device management and operator workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    list.mockResolvedValue({ devices: [windows, linux] });
    operations.mockResolvedValue({ operations: [] });
    switchDesktopTarget.mockResolvedValue({
      status: "accepted",
      request_id: null,
    });
    call.mockResolvedValue({
      hostname: "office-host",
      platform: "windows",
      capabilities: windows.capabilities,
      system: { cpu: "Ryzen 9", mainboard: "ASUS G513QM" },
    });
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: false,
    });
  });

  it("keeps capabilities out of management and opens the exact target in a workspace", async () => {
    show();
    await screen.findByText("Office Windows");
    expect(screen.queryByTestId("remote-desktop")).not.toBeInTheDocument();
    expect(screen.queryByTestId("remote-files")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("管理端工具"));
    expect(
      screen.getByRole("button", { name: "本机终端" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "本机浏览器" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "devices.desktopTab" }));
    await screen.findByTestId("remote-desktop");
    expect(screen.getByTestId("remote-desktop")).toHaveTextContent(
      "windows-office",
    );
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/devices?device=windows-office&view=desktop",
    );
    expect(screen.queryByText("devices.ledgerHint")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "返回设备" }));
    await screen.findByText("Office Windows");
    expect(screen.queryByTestId("remote-desktop")).not.toBeInTheDocument();
  });

  it("searches devices, clears empty results and keeps a specific workspace target", async () => {
    show();
    await screen.findByText("Office Windows");
    const search = screen.getByRole("textbox", {
      name: "devices.searchDevices",
    });
    fireEvent.change(search, { target: { value: "HEADLESS" } });
    expect(screen.queryByText("Office Windows")).not.toBeInTheDocument();
    expect(
      screen.getByRole("article", { name: "Headless Linux" }),
    ).toBeInTheDocument();
    fireEvent.change(search, { target: { value: "missing" } });
    expect(
      await screen.findByText("devices.noMatchingDevices"),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "devices.clearFilters" }),
    );
    const row = await screen.findByRole("article", { name: "Headless Linux" });
    fireEvent.click(
      within(row).getByRole("button", { name: "devices.openWorkspace" }),
    );
    expect(await screen.findByTestId("remote-files")).toHaveTextContent(
      "linux-headless",
    );
    expect(screen.getByTestId("location")).toHaveTextContent(
      "device=linux-headless&view=files",
    );
  });

  it("filters offline devices without treating revoked devices as offline", async () => {
    list.mockResolvedValue({
      devices: [
        windows,
        { ...linux, online: false },
        { ...linux, device_id: "revoked", name: "Revoked", revoked_at: 1 },
      ],
    });
    show();
    await screen.findByText("Office Windows");
    const filters = within(
      screen.getByRole("group", { name: "devices.filterDevices" }),
    );
    fireEvent.click(filters.getByRole("button", { name: /devices.offline/ }));
    expect(
      screen.getByRole("article", { name: "Headless Linux" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Office Windows")).not.toBeInTheDocument();
    expect(screen.queryByText("Revoked")).not.toBeInTheDocument();
    fireEvent.click(
      filters.getByRole("button", { name: /devices.allDevices/ }),
    );
    const revoked = screen.getByRole("article", { name: "Revoked" });
    expect(
      within(revoked).getByRole("button", { name: "devices.openWorkspace" }),
    ).toBeDisabled();
  });

  it("never substitutes another device for a missing deep-linked target", async () => {
    show("/devices?device=missing&view=desktop");
    await screen.findByText("此目标不存在或不属于当前账号，请返回设备列表。");
    expect(screen.queryByTestId("remote-desktop")).not.toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("device=missing");
  });

  it("does not expose desktop operations for a headless Linux client", async () => {
    show("/devices?device=linux-headless&view=desktop");
    await screen.findByText(
      "这台设备未授权或不支持此能力。Linux 无桌面客户端请使用文件或命令。",
    );
    expect(screen.queryByTestId("remote-desktop")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("devices.filesTab"));
    await screen.findByTestId("remote-files");
    expect(screen.getByTestId("remote-files")).toHaveTextContent(
      "linux-headless",
    );
  });

  it("shows operation records only on demand", async () => {
    show("/devices?device=windows-office&view=files");
    await screen.findByTestId("remote-files");
    expect(screen.queryByText("devices.ledgerHint")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "操作记录" }));
    await waitFor(() =>
      expect(screen.getByText("devices.ledgerHint")).toBeVisible(),
    );
  });

  it("renames an enrolled device from its card", async () => {
    update.mockImplementation(async () => {
      const renamed = { ...windows, name: "Desk PC" };
      list.mockResolvedValue({ devices: [renamed, linux] });
      return renamed;
    });
    show();
    await screen.findByText("Office Windows");
    fireEvent.click(
      screen.getAllByRole("button", { name: "devices.deviceActions" })[0],
    );
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "devices.rename" }),
    );
    fireEvent.change(
      screen.getByRole("textbox", { name: "devices.deviceName" }),
      { target: { value: "Desk PC" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "devices.rename" }));
    await waitFor(() =>
      expect(update).toHaveBeenCalledWith("windows-office", {
        name: "Desk PC",
      }),
    );
    expect(await screen.findByText("Desk PC")).toBeInTheDocument();
  });

  it("shows enrollment and live hardware details on demand", async () => {
    show();
    await screen.findByText("Office Windows");
    fireEvent.click(
      screen.getAllByRole("button", { name: "devices.deviceActions" })[0],
    );
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "devices.details" }),
    );
    expect(await screen.findByText("office-host")).toBeInTheDocument();
    expect(screen.getByText("Ryzen 9")).toBeInTheDocument();
    expect(screen.getByText("ASUS G513QM")).toBeInTheDocument();
    expect(call).toHaveBeenCalledWith(
      "windows-office",
      "status",
      {},
      expect.any(AbortSignal),
    );
  });

  it("keeps enrollment details available when a device is offline", async () => {
    list.mockResolvedValue({
      devices: [{ ...windows, online: false }, linux],
    });
    show();
    await screen.findByText("Office Windows");
    fireEvent.click(
      screen.getAllByRole("button", { name: "devices.deviceActions" })[0],
    );
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "devices.details" }),
    );
    expect(await screen.findByText("windows-office")).toBeInTheDocument();
    expect(screen.getByText("devices.detailsOffline")).toBeInTheDocument();
    expect(call).not.toHaveBeenCalled();
  });

  it("explains that legacy clients must be updated to report system details", async () => {
    call.mockResolvedValue({ hostname: "legacy-host", platform: "linux" });
    show();
    await screen.findByText("Office Windows");
    fireEvent.click(
      screen.getAllByRole("button", { name: "devices.deviceActions" })[0],
    );
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "devices.details" }),
    );
    expect(await screen.findByText("legacy-host")).toBeInTheDocument();
    expect(
      screen.getByText("devices.clientUpdateRequired"),
    ).toBeInTheDocument();
  });

  it("distinguishes unavailable virtual hardware from a missing client report", async () => {
    call.mockResolvedValue({
      hostname: "virtual-host",
      system: {
        os_version: "Ubuntu 24.04",
        architecture: "x86_64",
        cpu: "Xeon",
      },
    });
    show();
    await screen.findByText("Office Windows");
    fireEvent.click(
      screen.getAllByRole("button", { name: "devices.deviceActions" })[0],
    );
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "devices.details" }),
    );
    expect(await screen.findByText("Ubuntu 24.04")).toBeInTheDocument();
    expect(screen.getByText("devices.systemUnavailable")).toBeInTheDocument();
    expect(
      screen.queryByText("devices.clientUpdateRequired"),
    ).not.toBeInTheDocument();
  });

  it("releases the middle navigation pane for the operator workspace", () => {
    render(
      <MemoryRouter
        initialEntries={["/devices?device=windows-office&view=desktop"]}
      >
        <WorkspaceNav
          selectedKey="devices"
          collapsed={false}
          isMobile={false}
          onToggle={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
    expect(screen.getByRole("navigation")).toBeInTheDocument();
  });

  it("offers devices as the operator entry without duplicate host-tool navigation", () => {
    render(
      <MemoryRouter initialEntries={["/devices"]}>
        <WorkspaceNav
          selectedKey="devices"
          collapsed={false}
          isMobile={false}
          onToggle={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole("button", { name: "nav.devices" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "nav.workbench" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "nav.remoteDesktop" }),
    ).not.toBeInTheDocument();
  });
});
