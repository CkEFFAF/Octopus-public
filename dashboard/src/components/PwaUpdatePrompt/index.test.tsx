import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PwaUpdatePrompt from "./index";
import { updateApi } from "../../api/modules/update";
import { applyUpdate } from "../../pwa";

const { account } = vi.hoisted(() => ({
  account: { current: { role: "admin", permissions: [] as string[] } },
}));
vi.mock("../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => account.current,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../../api/modules/update", () => ({
  updateApi: { getUpdateStatus: vi.fn(), restartService: vi.fn() },
}));
vi.mock("../../pwa", () => ({ applyUpdate: vi.fn() }));

beforeEach(() => {
  vi.resetAllMocks();
  account.current = { role: "admin", permissions: [] };
});
async function openConfirmation() {
  render(<PwaUpdatePrompt />);
  act(() => {
    window.dispatchEvent(new Event("pwa:update-ready"));
  });
  fireEvent.click(screen.getByRole("button", { name: "pwa.updateNow" }));
  return await screen.findByRole("dialog");
}
describe("PWA update confirmation", () => {
  it("lets a user without update permission refresh the frontend without restarting the service", async () => {
    account.current = { role: "user", permissions: [] };
    vi.mocked(updateApi.getUpdateStatus).mockResolvedValue({
      service_mode: "systemd",
    } as Awaited<ReturnType<typeof updateApi.getUpdateStatus>>);
    const dialog = await openConfirmation();
    expect(
      within(dialog).getByText("uiFeedback.updatePage"),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByText("uiFeedback.updateService"),
    ).not.toBeInTheDocument();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "pwa.updateNow" }),
    );
    await waitFor(() => expect(applyUpdate).toHaveBeenCalledOnce());
    expect(updateApi.restartService).not.toHaveBeenCalled();
  });
  it("restarts the service only after confirmation and before applying the frontend update", async () => {
    vi.mocked(updateApi.getUpdateStatus).mockResolvedValue({
      service_mode: "systemd",
    } as Awaited<ReturnType<typeof updateApi.getUpdateStatus>>);
    const order: string[] = [];
    vi.mocked(updateApi.restartService).mockImplementation(async () => {
      order.push("restart");
      return {} as Awaited<ReturnType<typeof updateApi.restartService>>;
    });
    vi.mocked(applyUpdate).mockImplementation(async () => {
      order.push("apply");
    });
    const dialog = await openConfirmation();
    expect(order).toEqual([]);
    fireEvent.click(
      within(dialog).getByRole("button", { name: "pwa.updateNow" }),
    );
    await waitFor(() => expect(order).toEqual(["restart", "apply"]));
  });
  it("waits for explicit confirmation before restarting a service", async () => {
    vi.mocked(updateApi.getUpdateStatus).mockResolvedValue({
      service_mode: "systemd",
    } as Awaited<ReturnType<typeof updateApi.getUpdateStatus>>);
    const dialog = await openConfirmation();
    expect(
      within(dialog).getByText("uiFeedback.updateService"),
    ).toBeInTheDocument();
    expect(updateApi.restartService).not.toHaveBeenCalled();
    expect(applyUpdate).not.toHaveBeenCalled();
    expect(
      screen
        .getAllByRole("button", { name: "pwa.updateNow" })
        .find((button) => !dialog.contains(button)),
    ).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "pwa.later" }));
    expect(updateApi.restartService).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "pwa.updateNow" }),
      ).toBeEnabled(),
    );
  });
  it("reloads standalone pages only after confirming", async () => {
    vi.mocked(updateApi.getUpdateStatus).mockResolvedValue({
      service_mode: null,
    } as Awaited<ReturnType<typeof updateApi.getUpdateStatus>>);
    const dialog = await openConfirmation();
    expect(
      within(dialog).getByText("uiFeedback.updatePage"),
    ).toBeInTheDocument();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "pwa.updateNow" }),
    );
    await waitFor(() => expect(applyUpdate).toHaveBeenCalledOnce());
    expect(updateApi.restartService).not.toHaveBeenCalled();
  });
  it("keeps the page when service status cannot be read", async () => {
    vi.mocked(updateApi.getUpdateStatus).mockRejectedValue(
      new Error("offline"),
    );
    render(<PwaUpdatePrompt />);
    act(() => {
      window.dispatchEvent(new Event("pwa:update-ready"));
    });
    fireEvent.click(screen.getByRole("button", { name: "pwa.updateNow" }));
    await screen.findByText("uiFeedback.updateFailed");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(applyUpdate).not.toHaveBeenCalled();
  });
});
