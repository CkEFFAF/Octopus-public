import type { ChatMessage } from "../hooks/sseHelpers";
import type { ExpertPhase } from "../../../components/AnimatedExpertAvatar/model";
import { isAskHitl } from "../../../api/types/hitl";

export function toolAnimationPhase(name = "", args?: unknown): ExpertPhase {
  let input: Record<string, unknown> = {};
  try {
    const value = typeof args === "string" ? JSON.parse(args) : args;
    if (value && typeof value === "object") input = value;
  } catch {
    /* An incomplete streaming argument keeps the tool's default action. */
  }
  const action = typeof input.action === "string" ? input.action : "";
  const tool = `${name} ${action}`.toLowerCase();
  const params =
    input.params && typeof input.params === "object"
      ? (input.params as Record<string, unknown>)
      : input;
  const command = String(params.cmd ?? params.command ?? "");
  if (
    /exec|shell|terminal|process/.test(tool) &&
    /\b(pytest|vitest|tsc|eslint|ruff|mypy)\b|\b(npm|pnpm)\s+(run\s+)?(test|lint|check|build)\b/.test(
      command,
    )
  )
    return "verifying";
  if (/ask_user/.test(tool)) return "waiting_user";
  if (/permission|approval/.test(tool)) return "waiting_permission";
  if (/handoff|delegate/.test(tool)) return "handoff";
  if (
    /ask_agent|team|subagent|task_agent|collaborat|peer|send_message/.test(tool)
  )
    return "collaborating";
  if (/upload/.test(tool)) return "uploading";
  if (/download/.test(tool)) return "downloading";
  if (/imagegen|image_gen|draw|design/.test(tool)) return "drawing";
  if (/search|browse|web|fetch/.test(tool)) return "searching";
  if (/read|view|list_dir|glob|fs\.list|fs\.stat/.test(tool)) return "reading";
  if (/plan|todo/.test(tool)) return "planning";
  if (/test|check|verify|lint/.test(tool)) return "verifying";
  if (/edit|patch|write_file|code|fs\.write/.test(tool)) return "coding";
  if (/python|analy|chart|sql/.test(tool)) return "analyzing";
  if (/remind|cron|schedule/.test(tool)) return "reminder";
  if (/document|write|save/.test(tool)) return "writing";
  return "running";
}

/** Inspect only the latest user turn so old errors and approvals cannot override a new run. */
export function chatAnimationPhase(
  messages: ChatMessage[],
  running: boolean,
): ExpertPhase {
  let lastUser = messages.length - 1;
  while (lastUser >= 0 && messages[lastUser].role !== "user") lastUser--;
  const turn = messages.slice(lastUser + 1);
  const pending = turn
    .filter((m) => m.hitlData && (m.hitlData.status ?? "pending") === "pending")
    .at(-1);
  if (pending?.hitlData)
    return isAskHitl(pending.hitlData.action_requests)
      ? "waiting_user"
      : "waiting_permission";
  const last = turn.at(-1);
  if (last?.status === "error") return "error";
  if (!running) return "idle";
  const tool = turn
    .filter(
      (m) =>
        m.toolData && m.toolData.output === undefined && m.status !== "error",
    )
    .at(-1);
  if (tool)
    return toolAnimationPhase(tool.toolData?.name, tool.toolData?.arguments);
  if (
    last?.type === "thinking" ||
    last?.type === "reasoning" ||
    last?.contentBlocks?.at(-1)?.type === "thinking"
  )
    return "thinking";
  if (last?.content?.trim()) return "speaking";
  return "thinking";
}
