import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import CostMeterDock from "./CostMeterDock";
import { useCostMeter } from "./useCostMeter";
import type { CostMeterState } from "../../api/modules/pluginMarket";

vi.mock("./useCostMeter", () => ({ useCostMeter: vi.fn() }));
vi.mock("./CostMeterSettings", () => ({ default: () => null }));

const state = {
  installation: { installed: true, enabled: true, show_in_chat: true },
  peak: { in_peak: false, next_change_at: "2026-11-09T01:00:00Z" },
  go: { status: "ok", rolling: { percent: 17, resets_at: null } },
} as CostMeterState;

describe("chat quota freshness", () => {
  it.each([true, false])(
    "labels stale data after an HTTP or upstream error (%s)",
    (connectionError) => {
      vi.mocked(useCostMeter).mockReturnValue({
        state: {
          ...state,
          go: { ...state.go, status: connectionError ? "ok" : "error" },
        },
        error: connectionError,
        busy: false,
        now: Date.parse("2026-11-08T00:00:00Z"),
        refresh: vi.fn(),
      });
      render(
        <MemoryRouter>
          <CostMeterDock />
        </MemoryRouter>,
      );
      expect(screen.getByRole("status")).toHaveTextContent(
        "pluginMarket.refreshFailed",
      );
      expect(screen.queryByText("Go 17%")).not.toBeInTheDocument();
    },
  );
  it("displays a healthy quota without a failure label", () => {
    vi.mocked(useCostMeter).mockReturnValue({
      state,
      error: false,
      busy: false,
      now: Date.parse("2026-11-08T00:00:00Z"),
      refresh: vi.fn(),
    });
    render(
      <MemoryRouter>
        <CostMeterDock />
      </MemoryRouter>,
    );
    expect(screen.getByText("Go 17%")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
