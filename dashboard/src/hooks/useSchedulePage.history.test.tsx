import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { octopCronApi } from "../api/modules/cronjob";
import { useSchedulePage } from "./useSchedulePage";

vi.mock("../api/modules/cronjob", () => ({ octopCronApi: { page: vi.fn() } }));
afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});
const empty = {
  items: [],
  total: 0,
  has_more: false,
  next_offset: null,
  counts: { schedules: 0, reminders: 0 },
};

it("loads archived schedules on demand without repeatedly polling them", async () => {
  vi.useFakeTimers();
  vi.mocked(octopCronApi.page).mockResolvedValue(empty);
  const { result } = renderHook(() =>
    useSchedulePage({ lifecycle: "archived" }),
  );
  await act(async () => {
    await Promise.resolve();
  });
  expect(result.current.loading).toBe(false);
  expect(octopCronApi.page).toHaveBeenCalledTimes(1);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(60000);
  });
  expect(octopCronApi.page).toHaveBeenCalledTimes(1);
  await act(async () => {
    await result.current.refresh();
  });
  expect(octopCronApi.page).toHaveBeenCalledTimes(2);
});

it("does not fetch a second copy of an inactive scope subscription", async () => {
  vi.mocked(octopCronApi.page).mockResolvedValue(empty);
  const view = renderHook(
    ({ enabled }) => useSchedulePage({ lifecycle: "active" }, enabled),
    { initialProps: { enabled: false } },
  );
  expect(octopCronApi.page).not.toHaveBeenCalled();
  await act(async () => {
    view.rerender({ enabled: true });
  });
  expect(octopCronApi.page).toHaveBeenCalledTimes(1);
});
