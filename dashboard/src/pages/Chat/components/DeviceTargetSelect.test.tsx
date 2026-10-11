import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { devicesApi, type Device } from "../../../api/modules/devices";
import DeviceTargetSelect from "./DeviceTargetSelect";

vi.mock("../../../api/modules/devices", () => ({
  devicesApi: { list: vi.fn() },
}));

describe("DeviceTargetSelect", () => {
  beforeEach(() => vi.mocked(devicesApi.list).mockReset());

  it("does not reserve a row when no devices are enrolled", async () => {
    vi.mocked(devicesApi.list).mockResolvedValue({ devices: [] });
    const { container } = render(<DeviceTargetSelect />);

    await waitFor(() => expect(devicesApi.list).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("shows an available device and the management entry", async () => {
    vi.mocked(devicesApi.list).mockResolvedValue({
      devices: [
        {
          device_id: "device-1",
          name: "Office PC",
          online: true,
          revoked_at: null,
        } as Device,
      ],
    });
    render(<DeviceTargetSelect />);

    expect(await screen.findByRole("combobox")).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/devices");
  });
});
