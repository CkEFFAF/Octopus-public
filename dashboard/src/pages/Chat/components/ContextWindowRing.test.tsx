import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ContextWindowRing from "./ContextWindowRing";
import {
  octopThreadsApi,
  type ContextUsageBreakdown,
} from "../../../api/modules/octopThreads";

vi.mock("../../../api/modules/octopThreads", () => ({
  octopThreadsApi: { contextUsage: vi.fn() },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const result = (used: number, capacity = 1_000_000): ContextUsageBreakdown => ({
  used_tokens: used,
  max_tokens: capacity,
  capacity_tokens: capacity,
  capacity_source: "model",
  segments: [],
});
const base = {
  agentId: "gpu",
  threadId: "t",
  usedTokens: 418_748,
  maxTokens: 1_000_000,
};
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("context occupancy ring", () => {
  it("uses catalog capacity while the selected model save is still pending", async () => {
    vi.mocked(octopThreadsApi.contextUsage).mockResolvedValue(
      result(50_000, 1_000_000),
    );
    render(
      <ContextWindowRing
        {...base}
        usedTokens={50_000}
        maxTokens={128_000}
        selectedModel="p/small"
        selectedCapacityTokens={128_000}
      />,
    );
    await waitFor(() =>
      expect(octopThreadsApi.contextUsage).toHaveBeenCalledTimes(1),
    );
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe(
      "39",
    );
  });
  it("loads canonical capacity even with connectors, refreshes after usage and model changes", async () => {
    const load = vi.mocked(octopThreadsApi.contextUsage);
    load
      .mockResolvedValueOnce(result(418_748))
      .mockResolvedValueOnce(result(500_000))
      .mockResolvedValueOnce(result(50_000, 128_000));
    const { rerender } = render(
      <ContextWindowRing {...base} selectedConnectors={["search"]} />,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("progressbar").getAttribute("aria-valuenow"),
      ).toBe("42"),
    );
    expect(load).toHaveBeenCalledWith("gpu", "t");
    rerender(
      <ContextWindowRing
        {...base}
        usedTokens={500_000}
        selectedConnectors={["search"]}
      />,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("progressbar").getAttribute("aria-valuenow"),
      ).toBe("50"),
    );
    rerender(
      <ContextWindowRing
        {...base}
        usedTokens={50_000}
        selectedModel="p/small"
        maxTokens={128_000}
      />,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("progressbar").getAttribute("aria-valuenow"),
      ).toBe("39"),
    );
    expect(load).toHaveBeenCalledTimes(3);
  });

  it("ignores late responses from the previous thread", async () => {
    let finish!: (data: ContextUsageBreakdown) => void;
    vi.mocked(octopThreadsApi.contextUsage)
      .mockReturnValueOnce(
        new Promise((resolve) => {
          finish = resolve;
        }),
      )
      .mockResolvedValueOnce(result(200_000));
    const { rerender } = render(<ContextWindowRing {...base} />);
    rerender(<ContextWindowRing {...base} threadId="other" />);
    await waitFor(() =>
      expect(
        screen.getByRole("progressbar").getAttribute("aria-valuenow"),
      ).toBe("20"),
    );
    await act(async () => {
      finish(result(900_000));
    });
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe(
      "20",
    );
  });

  it("keeps truly unknown capacity unknown", async () => {
    vi.mocked(octopThreadsApi.contextUsage).mockResolvedValue({
      ...result(42_000),
      capacity_tokens: null,
      capacity_source: "compatibility_default",
    });
    render(<ContextWindowRing {...base} />);
    await waitFor(() =>
      expect(octopThreadsApi.contextUsage).toHaveBeenCalledTimes(1),
    );
    expect(screen.getByRole("progressbar").hasAttribute("aria-valuenow")).toBe(
      false,
    );
  });
});
