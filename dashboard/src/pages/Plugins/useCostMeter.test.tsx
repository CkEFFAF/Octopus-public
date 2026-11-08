import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CostMeterState } from "../../api/modules/pluginMarket";
import { pluginMarketApi } from "../../api/modules/pluginMarket";
import { useCostMeter } from "./useCostMeter";

const identity = vi.hoisted(() => ({ id: 1 }));
vi.mock("../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ id: identity.id }),
}));
vi.mock("../../api/modules/pluginMarket", () => ({
  PLUGIN_MARKET_CHANGED: "plugins-test-changed",
  pluginMarketApi: { refresh: vi.fn(), state: vi.fn() },
}));

function snapshot(percent: number): CostMeterState {
  return {
    installation: { installed: true, enabled: true, show_in_chat: true },
    server_time: new Date().toISOString(),
    peak: {
      in_peak: false,
      reason: "weekday",
      next_change_at: new Date(Date.now() + 3600_000).toISOString(),
      calendar_supported: true,
      timezone: "Asia/Shanghai",
    },
    go: {
      status: "ok",
      error_code: null,
      fetched_at: null,
      attempted_at: null,
      rolling: { percent, resets_at: null },
      weekly: null,
      monthly: null,
    },
    key_configured: true,
    subscription_expires_at: null,
    subscription_source: null,
  };
}

describe("cost meter account boundaries", () => {
  beforeEach(() => {
    identity.id = 1;
    vi.resetAllMocks();
  });

  it("hides the previous account immediately and ignores its late response", async () => {
    let finishOld!: (value: CostMeterState) => void;
    let finishNew!: (value: CostMeterState) => void;
    vi.mocked(pluginMarketApi.refresh)
      .mockResolvedValueOnce(snapshot(17))
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finishOld = resolve;
          }),
      )
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finishNew = resolve;
          }),
      );
    const { result, rerender } = renderHook(() => useCostMeter());
    await waitFor(() =>
      expect(result.current.state?.go.rolling?.percent).toBe(17),
    );
    let oldRequest!: Promise<void>;
    act(() => {
      oldRequest = result.current.refresh(true);
    });
    identity.id = 2;
    rerender();
    expect(result.current.state).toBeNull();
    await act(async () => {
      finishOld(snapshot(99));
      await oldRequest;
    });
    expect(result.current.state).toBeNull();
    await act(async () => {
      finishNew(snapshot(42));
    });
    expect(result.current.state?.go.rolling?.percent).toBe(42);
  });
});
