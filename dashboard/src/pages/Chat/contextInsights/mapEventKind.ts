/** Map trajectory / run-event kinds onto Insights Events chips (spec 0020 S2).
 * Keep in lockstep with `octop.infra.context_insights.mapping.map_event_kind`.
 */
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

const RUN_EVENT_MAP: Record<string, MappedContextKind> = {
  model: "model",
  device: "switch",
  workflow: "mode",
  job: "other",
  interaction: "other",
};

const MAPPED_KINDS = new Set<MappedContextKind>([
  "inject",
  "compact",
  "prune",
  "switch",
  "mode",
  "model",
  "user",
  "assistant",
  "tool",
  "other",
]);

function asTruthyFlag(value: unknown): boolean {
  if (value === true) return true;
  const text = String(value ?? "")
    .trim()
    .toLowerCase();
  return text === "1" || text === "true" || text === "yes";
}

export function mapTrajectoryKind(
  rawKind: string,
  payload?: Record<string, unknown> | null,
): MappedContextKind {
  const kind = (rawKind || "").trim().toLowerCase();
  const mapped = TRAJECTORY_MAP[kind];
  const data = payload ?? {};
  if (mapped === "compact") return "compact";
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
  if (asTruthyFlag(data.prune) || asTruthyFlag(data.pruned)) return "prune";
  const producer = String(data.producer ?? data.source ?? "").toLowerCase();
  if (producer.includes("model") || kind === "model") return "model";
  if (kind === "mode" || kind === "switch") return kind;
  return mapped && MAPPED_KINDS.has(mapped) ? mapped : "other";
}

/** Align with Python ``map_event_kind(..., source="run_event")``. */
export function mapRunEventKind(
  rawKind: string,
  payload?: Record<string, unknown> | null,
): MappedContextKind {
  const kind = (rawKind || "").trim().toLowerCase();
  const mapped = RUN_EVENT_MAP[kind];
  if (mapped) return mapped;
  const data = payload ?? {};
  const mode = String(data.work_mode ?? data.conversation_mode ?? "").trim();
  if (mode) return "mode";
  return "other";
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
  "switch",
  "mode",
  "model",
  "user",
  "assistant",
  "tool",
  "other",
];
