import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  workItemsApi,
  type WorkItemDetail,
} from "../../../api/modules/workItems";
import { useWorkItems } from "./useWorkItems";
vi.mock("../../../api/modules/workItems", () => ({
  workItemsApi: { list: vi.fn(), detail: vi.fn() },
}));
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(workItemsApi.list).mockResolvedValue({
    items: [],
    has_more: false,
  });
});
it("ignores a late list from the previous conversation", async () => {
  let resolve!: (value: { items: WorkItemDetail[]; has_more: boolean }) => void;
  vi.mocked(workItemsApi.list).mockImplementationOnce(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  const { result, rerender } = renderHook(
    ({ id }) => useWorkItems(id, false, null),
    { initialProps: { id: "one" } },
  );
  rerender({ id: "two" });
  await waitFor(() => expect(workItemsApi.list).toHaveBeenCalledWith("two"));
  await act(async () =>
    resolve({ items: [{ task_id: "old" } as WorkItemDetail], has_more: false }),
  );
  expect(result.current.items).toEqual([]);
});
