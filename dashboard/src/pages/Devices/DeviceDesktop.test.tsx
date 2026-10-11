import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Device } from "../../api/modules/devices";

const { call } = vi.hoisted(() => ({ call: vi.fn() }));
vi.mock("../../api/modules/devices", () => ({ devicesApi: { call } }));

import DeviceDesktop from "./DeviceDesktop";

const device: Device = {
  device_id: "chosen-device",
  name: "Office computer",
  platform: "windows",
  capabilities: ["desktop_view", "desktop_control"],
  permissions: ["desktop_view", "desktop_control"],
  roots: [],
  grant_version: 1,
  online: true,
  revoked_at: null,
  last_seen_at: null,
};
const frame = { jpeg_b64: "image", width: 1920, height: 1080 };

describe("device desktop user controls", () => {
  beforeEach(() => {
    call.mockReset();
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: false,
    });
  });
  afterEach(() => vi.useRealTimers());

  it("does not capture before a user starts viewing", () => {
    render(<DeviceDesktop device={device} onError={vi.fn()} />);
    expect(call).not.toHaveBeenCalled();
    expect(screen.getByRole("switch")).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "devices.sendKey" }),
    ).toBeDisabled();
  });

  it("never overlaps capture requests and stops polling on stop", async () => {
    vi.useFakeTimers();
    let resolve: (value: typeof frame) => void = () => {};
    call.mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    render(<DeviceDesktop device={device} onError={vi.fn()} />);
    fireEvent.click(
      screen.getByRole("button", { name: "devices.startViewing" }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(call).toHaveBeenCalledTimes(1);
    expect(call.mock.calls[0].slice(0, 3)).toEqual([
      "chosen-device",
      "desktop.capture",
      { quality: 65 },
    ]);
    await act(async () => {
      resolve(frame);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(call).toHaveBeenCalledTimes(2);
    const signal = call.mock.calls[1][3] as AbortSignal;
    fireEvent.click(
      screen.getByRole("button", { name: "devices.stopViewing" }),
    );
    expect(signal.aborted).toBe(true);
    await act(async () => {
      resolve(frame);
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(call).toHaveBeenCalledTimes(2);
  });

  it("keeps viewing-only permission separate from keyboard input", async () => {
    call.mockResolvedValue(frame);
    render(
      <DeviceDesktop
        device={{ ...device, permissions: ["desktop_view"] }}
        onError={vi.fn()}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "devices.startViewing" }),
    );
    await waitFor(() => expect(screen.getByRole("img")).toBeInTheDocument());
    expect(screen.getByRole("switch")).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "devices.sendKey" }),
    ).toBeDisabled();
    expect(call.mock.calls.every((args) => args[1] === "desktop.capture")).toBe(
      true,
    );
  });
});
