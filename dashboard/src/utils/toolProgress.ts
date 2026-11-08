import { summarizeHitlAction } from "../pages/Chat/utils/summarizeHitlAction";

export type ProgressTranslate = (
  key: string,
  options?: Record<string, unknown>,
) => string;

function record(value: unknown): Record<string, unknown> {
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch {
      return {};
    }
  }
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/** Explain observed tool activity locally, without another model call or guessed progress. */
export function toolProgress(
  toolName: string | undefined,
  args: unknown,
  output: unknown,
  t: ProgressTranslate,
  status?: string,
) {
  const name = toolName || "";
  const translated = t(`tools.${name}`);
  const label =
    translated !== `tools.${name}`
      ? translated
      : t("chat.toolFeedback.external");
  const input = record(args);
  let action = summarizeHitlAction(
    name,
    input,
    (key, options) =>
      t(key, typeof options === "string" ? { defaultValue: options } : options),
    label,
  ).summary;
  if (["execute", "bash", "run_terminal_cmd", "shell"].includes(name)) {
    // The activity line is a summary. Full scripts remain in tool details and approvals.
    const command = String(input.command || input.cmd || "");
    const program = command.match(
      /(?:^|&&|\|\||[;\n])\s*(?:[^\s"']*[\\/])?(python(?:\d+(?:\.\d+)?)?|node|npm|pnpm|uv|git|pytest|curl)\b/i,
    )?.[1];
    action = program
      ? t("chat.toolFeedback.runProgram", {
          program: /^python/i.test(program) ? "Python" : program,
        })
      : t("chat.toolFeedback.runCommand");
  }
  if (["job_status", "job_logs", "job_cancel"].includes(name))
    action = t(`chat.toolFeedback.${name}`);
  if (name === "read_attachment")
    action = t("chat.toolFeedback.readAttachment", {
      name:
        String(input.filename || input.path || "")
          .split(/[\\/]/)
          .pop() || t("chat.toolFeedback.attachedFile"),
    });
  if (name === "job_start") action = t("chat.toolFeedback.startJob");
  const body = record(output);
  const result = record(body.result);
  const receipt = Object.keys(result).length ? result : body;
  const failed =
    status === "error" ||
    !!body.error ||
    !!receipt.error ||
    receipt.status === "error" ||
    receipt.status === "failed" ||
    (typeof receipt.returncode === "number" && receipt.returncode !== 0);
  const running = ["running", "queued", "accepted", "started"].includes(
    String(receipt.status),
  );
  const outcome =
    output === undefined
      ? t("common.running")
      : failed
      ? t("chat.toolFeedback.failed")
      : running
      ? t("chat.toolFeedback.backgroundRunning")
      : t("chat.toolFeedback.returned");
  const facts: string[] = [];
  if (typeof receipt.returncode === "number")
    facts.push(t("chat.toolFeedback.exitCode", { code: receipt.returncode }));
  if (typeof receipt.size === "number")
    facts.push(t("chat.toolFeedback.bytes", { count: receipt.size }));
  if (typeof receipt.total_lines === "number")
    facts.push(t("chat.toolFeedback.lines", { count: receipt.total_lines }));
  if (typeof receipt.status === "string" && receipt.status === "ready")
    facts.push(t("chat.toolFeedback.resourceReady"));
  return {
    label,
    action: action.length > 160 ? `${action.slice(0, 159)}…` : action,
    outcome,
    facts,
    failed,
  };
}
