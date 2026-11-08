import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  executionApi,
  type RequestSnapshot,
} from "../../../api/modules/execution";
import {
  recentCompletedRequest,
  useRecentRequestUsage,
} from "./useRecentRequestUsage";

const auth = vi.hoisted(() => ({ id: 1 }));
vi.mock("../../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => auth,
}));
vi.mock("../../../api/modules/execution", () => ({
  executionApi: { recentRequests: vi.fn() },
}));
const row = (
  seq: number,
  actual_usage: RequestSnapshot["actual_usage"],
  status = "completed",
) =>
  ({
    request_id: `r${seq}`,
    seq,
    created_at: seq,
    status,
    actual_usage,
  }) as RequestSnapshot;
const page = (requests: RequestSnapshot[]) => ({
  requests,
  has_more: false,
  next_before: null,
});
beforeEach(() => {
  vi.clearAllMocks();
  auth.id = 1;
});
afterEach(() => vi.restoreAllMocks());

it("uses the latest completed request, independently of a newer unfinished call", () => {
  const result = recentCompletedRequest([
    row(3, null, "started"),
    row(1, {
      input_tokens: 100,
      cache_read_tokens: 0,
      cache_metrics_reported: true,
    }),
    row(2, {
      input_tokens: 100,
      cache_read_tokens: 99,
      cache_metrics_reported: true,
    }),
  ]);
  expect(result?.request_id).toBe("r2");
  expect(result?.actual_usage?.cache_read_tokens).toBe(99);
});
it("preserves a reported cold zero and keeps legacy or unknown zero unavailable", () => {
  expect(
    recentCompletedRequest([
      row(1, {
        input_tokens: 100,
        cache_read_tokens: 0,
        cache_metrics_reported: true,
      }),
    ])?.actual_usage?.cache_read_tokens,
  ).toBe(0);
  expect(
    recentCompletedRequest([
      row(1, { input_tokens: 100, cache_read_tokens: 0 }),
    ])?.actual_usage?.cache_read_tokens,
  ).toBeUndefined();
  expect(
    recentCompletedRequest([
      row(1, {
        input_tokens: 100,
        cache_read_tokens: 90,
        cache_metrics_reported: false,
      }),
    ])?.actual_usage?.cache_read_tokens,
  ).toBeUndefined();
});
it("does not replace an unknown latest result with an older high hit rate", () => {
  const result = recentCompletedRequest([
    row(1, { input_tokens: 100, cache_read_tokens: 99 }),
    row(2, { input_tokens: 100, cache_read_tokens: 0 }),
  ]);
  expect(result?.request_id).toBe("r2");
  expect(result?.actual_usage?.cache_metrics_reported).toBe(false);
});
it("refreshes active calls without waiting for an assistant answer to finish", async () => {
  vi.mocked(executionApi.recentRequests)
    .mockResolvedValueOnce(
      page([
        row(1, {
          input_tokens: 100,
          cache_read_tokens: 0,
          cache_metrics_reported: true,
        }),
      ]),
    )
    .mockResolvedValue(
      page([
        row(2, {
          input_tokens: 100,
          cache_read_tokens: 98,
          cache_metrics_reported: true,
        }),
      ]),
    );
  const interval = vi.spyOn(window, "setInterval");
  const clear = vi.spyOn(window, "clearInterval");
  const view = renderHook(() => useRecentRequestUsage("agent", "thread", true));
  await waitFor(() => expect(view.result.current.entry?.request_id).toBe("r1"));
  expect(interval).toHaveBeenCalledWith(expect.any(Function), 5000);
  act(() => window.dispatchEvent(new Event("focus")));
  await waitFor(() =>
    expect(view.result.current.entry?.actual_usage?.cache_read_tokens).toBe(98),
  );
  view.unmount();
  expect(clear).toHaveBeenCalled();
});
it("ignores late responses from another thread or account", async () => {
  let resolveOld!: (value: ReturnType<typeof page>) => void;
  vi.mocked(executionApi.recentRequests)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOld = resolve;
        }),
    )
    .mockResolvedValue(
      page([row(2, { input_tokens: 100, cache_read_tokens: 80 })]),
    );
  const view = renderHook(
    ({ thread }) => useRecentRequestUsage("agent", thread),
    { initialProps: { thread: "old" } },
  );
  view.rerender({ thread: "new" });
  await waitFor(() => expect(view.result.current.entry?.request_id).toBe("r2"));
  await act(async () =>
    resolveOld(page([row(1, { input_tokens: 100, cache_read_tokens: 1 })])),
  );
  expect(view.result.current.entry?.request_id).toBe("r2");
  auth.id = 2;
  vi.mocked(executionApi.recentRequests).mockReturnValue(new Promise(() => {}));
  view.rerender({ thread: "new" });
  expect(view.result.current.entry).toBeNull();
});
it("hides stale results when refresh fails", async () => {
  vi.mocked(executionApi.recentRequests)
    .mockResolvedValueOnce(
      page([row(1, { input_tokens: 100, cache_read_tokens: 99 })]),
    )
    .mockRejectedValue(new Error("offline"));
  const view = renderHook(() => useRecentRequestUsage("agent", "thread", true));
  await waitFor(() => expect(view.result.current.entry?.request_id).toBe("r1"));
  act(() => window.dispatchEvent(new Event("focus")));
  await waitFor(() => expect(view.result.current.failed).toBe(true));
  expect(view.result.current.entry).toBeNull();
});
it("looks past failed and unfinished pages for the latest completed receipt", async () => {
  vi.mocked(executionApi.recentRequests)
    .mockResolvedValueOnce({
      requests: [
        row(5, null, "failed"),
        row(4, null, "cancelled"),
        row(3, null, "started"),
      ],
      has_more: true,
      next_before: 3,
    })
    .mockResolvedValueOnce(
      page([row(2, { input_tokens: 100, cache_read_tokens: 99 })]),
    );
  const view = renderHook(() => useRecentRequestUsage("agent", "thread"));
  await waitFor(() => expect(view.result.current.entry?.request_id).toBe("r2"));
  expect(executionApi.recentRequests).toHaveBeenNthCalledWith(
    2,
    "agent",
    "thread",
    3,
  );
});
