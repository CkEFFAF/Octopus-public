/** Map trajectory kinds onto Insights Events chips (spec 0020 S2). */
export type MappedContextKind =
  | "inject"
  | "compact"
  | "prune"
  | "switch"
  | "mode"
  | "model"
  | "user"
  | "assistant"
  | "tool"
  | "other";

const TRAJECTORY_MAP: Record<string, MappedContextKind> = {
  compacted: "compact",
  context: "inject",
  system: "inject",
  user: "user",
  assistant: "assistant",
  tool: "tool",
};

export function mapTrajectoryKind(
  rawKind: string,
  payload?: Record<string, unknown> | null,
): MappedContextKind {
  const kind = (rawKind || "").toLowerCase();
  const mapped = TRAJECTORY_MAP[kind];
  const data = payload ?? {};
  const transformation = data.transformation;
  if (
    transformation &&
    typeof transformation === "object" &&
    "kind" in transformation
  ) {
    const tKind = String((transformation as { kind?: string }).kind || "");
    if (tKind === "prune") return "prune";
    if (tKind === "summarization" || tKind === "message_rewrite") return "compact";
  }
  if (data.prune === true || data.pruned === true) return "prune";
  return mapped ?? "other";
}

export function isCompactMark(
  rawKind: string,
  payload?: Record<string, unknown> | null,
): boolean {
  const mapped = mapTrajectoryKind(rawKind, payload);
  return mapped === "compact" || mapped === "prune" || rawKind === "compacted";
}

export const MAPPED_KIND_FILTERS: Array<MappedContextKind | "all"> = [
  "all",
  "inject",
  "compact",
  "prune",
  "user",
  "assistant",
  "tool",
  "other",
];
