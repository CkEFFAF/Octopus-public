import { describe, expect, it } from "vitest";
import { isCapacityResolved, occupancyPercent } from "./capacity";

describe("isCapacityResolved", () => {
  it("accepts model metadata and explicit real 128k capacity", () => {
    expect(occupancyPercent(418_748, 1_000_000, "model")).toBeCloseTo(41.8748);
    expect(isCapacityResolved("agent_config", 128_000)).toBe(true);
  });
  it("treats harness capacity as resolved", () => {
    expect(isCapacityResolved("harness", 200_000)).toBe(true);
  });

  it("rejects compatibility 128k default", () => {
    expect(isCapacityResolved("compatibility_default", null)).toBe(false);
    expect(isCapacityResolved("compatibility_default", 128_000)).toBe(false);
  });

  it("rejects missing / unknown capacity", () => {
    expect(isCapacityResolved(undefined, null)).toBe(false);
    expect(isCapacityResolved("harness", null)).toBe(false);
    expect(isCapacityResolved("harness", 0)).toBe(false);
    expect(isCapacityResolved("capacity_unresolved", 128_000)).toBe(false);
  });
});

describe("occupancyPercent", () => {
  it("returns a real percent against harness capacity", () => {
    expect(occupancyPercent(25_000, 100_000, "harness")).toBe(25);
  });

  it("returns null for compatibility default (no fake precision)", () => {
    expect(occupancyPercent(4200, 128_000, "compatibility_default")).toBe(null);
  });

  it("returns 0 when unused against a resolved window", () => {
    expect(occupancyPercent(0, 100_000, "harness")).toBe(0);
  });
});
