/**
 * DEC-T05 / REQ-A3 / UI03: compatibility 128k and unresolved capacity must not
 * be presented as a precise occupancy percentage.
 */
export type CapacitySource =
  | "harness"
  | "compatibility_default"
  | string
  | null
  | undefined;

export function isCapacityResolved(
  capacitySource?: CapacitySource,
  capacityTokens?: number | null,
): boolean {
  if (capacitySource === "compatibility_default") return false;
  if (["harness", "model", "agent_config"].includes(capacitySource ?? "")) {
    return typeof capacityTokens === "number" && capacityTokens > 0;
  }
  // Missing / unknown / capacity_unresolved → do not invent precision.
  return false;
}

/** Occupancy % only when capacity is a real harness window; else null. */
export function occupancyPercent(
  usedTokens: number | null | undefined,
  capacityTokens: number | null | undefined,
  capacitySource?: CapacitySource,
): number | null {
  if (!isCapacityResolved(capacitySource, capacityTokens)) return null;
  const used = typeof usedTokens === "number" ? usedTokens : 0;
  const max = capacityTokens as number;
  if (max <= 0) return null;
  if (used <= 0) return 0;
  return Math.min(100, (used / max) * 100);
}
