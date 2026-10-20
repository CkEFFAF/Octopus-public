import { describe, expect, it } from "vitest";
import type { Device } from "../../api/modules/devices";
import {
  canUse,
  desktopPoint,
  selectedDeviceId,
  deviceWorkspaceUrl,
  workspaceView,
  supportsWorkspaceView,
  nativeParentPath,
} from "./helpers";

const device: Device = {
  device_id: "windows-a",
  name: "Office",
  platform: "windows",
  capabilities: ["desktop_view", "desktop_control"],
  permissions: ["desktop_view", "desktop_control"],
  roots: [],
  grant_version: 1,
  online: true,
  last_seen_at: null,
  revoked_at: null,
};

describe("native parent directory navigation", () => {
  it.each([
    ["D:/samples/workspace", true, "D:/samples"],
    ["D:/samples/", true, "D:/"],
    ["D:/", true, "D:/"],
    [String.raw`D:\samples\workspace`, true, String.raw`D:\samples`],
    ["D:\\", true, "D:\\"],
    [String.raw`\\server\share\folder`, true, String.raw`\\server\share`],
    ["\\\\server\\share\\", true, String.raw`\\server\share`],
    ["/home/owner/workspace/", false, "/home/owner"],
    ["/home", false, "/"],
    ["/", false, "/"],
    ["/home/../", false, "/home/../.."],
    [".", false, "./.."],
  ])("%s → %s", (path, windows, expected) => {
    expect(nativeParentPath(path, windows)).toBe(expected);
  });
});

describe("device permission gates", () => {
  it("requires both desktop grants for input", () => {
    expect(canUse(device, "desktop_control")).toBe(true);
    expect(
      canUse(
        { ...device, permissions: ["desktop_control"] },
        "desktop_control",
      ),
    ).toBe(false);
    expect(
      canUse({ ...device, capabilities: ["desktop_view"] }, "desktop_control"),
    ).toBe(false);
  });
  it("blocks offline and revoked devices", () => {
    expect(canUse({ ...device, online: false }, "desktop_view")).toBe(false);
    expect(canUse({ ...device, revoked_at: 1 }, "desktop_view")).toBe(false);
  });
});

describe("device selection", () => {
  it("keeps an explicit target when the list order changes", () => {
    const second = { ...device, device_id: "linux-b" };
    expect(selectedDeviceId([second, device], device.device_id)).toBe(
      "windows-a",
    );
    expect(selectedDeviceId([{ ...device, revoked_at: 1 }, second], "")).toBe(
      "linux-b",
    );
  });
});

describe("device workspace routing", () => {
  it("encodes explicit targets and only accepts supported view names", () => {
    expect(deviceWorkspaceUrl("office & desk", "desktop")).toBe(
      "/devices?device=office+%26+desk&view=desktop",
    );
    expect(workspaceView("desktop")).toBe("desktop");
    expect(workspaceView("permissions")).toBeNull();
    expect(workspaceView(null)).toBeNull();
  });
  it("offers offline workspaces without granting execution or headless desktops", () => {
    expect(supportsWorkspaceView({ ...device, online: false }, "desktop")).toBe(
      true,
    );
    expect(canUse({ ...device, online: false }, "desktop_view")).toBe(false);
    expect(
      supportsWorkspaceView(
        {
          ...device,
          capabilities: ["command_exec"],
          permissions: ["command_exec"],
        },
        "desktop",
      ),
    ).toBe(false);
    expect(supportsWorkspaceView({ ...device, revoked_at: 1 }, "desktop")).toBe(
      false,
    );
  });
});

describe("desktop input coordinates", () => {
  const bounds = { left: 20, top: 30, width: 360, height: 200 };
  const screen = { width: 1920, height: 1080 };
  it("maps mobile image coordinates to device pixels and clamps edges", () => {
    expect(desktopPoint(200, 130, bounds, screen)).toEqual({ x: 960, y: 540 });
    expect(desktopPoint(380, 230, bounds, screen)).toEqual({
      x: 1919,
      y: 1079,
    });
  });
  it("ignores clicks outside the image or before geometry is known", () => {
    expect(desktopPoint(0, 0, bounds, screen)).toBeNull();
    expect(desktopPoint(200, 130, { ...bounds, width: 0 }, screen)).toBeNull();
  });
  it("retains a monitor's native offset after scaling", () => {
    expect(
      desktopPoint(200, 130, bounds, { ...screen, left: -1920, top: -1080 }),
    ).toEqual({ x: -960, y: -540 });
  });
});
