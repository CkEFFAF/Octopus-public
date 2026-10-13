export type WorkMode =
  | "agentic"
  | "plan"
  | "debug"
  | "multitask"
  | "cowork"
  | "computer_use"
  | "deep_research"
  | "team"
  | "ask";

export const WORK_MODES: readonly WorkMode[] = [
  "agentic",
  "plan",
  "debug",
  "multitask",
  "cowork",
  "computer_use",
  "deep_research",
  "team",
  "ask",
];

const INSTRUCTIONS: Record<
  Exclude<WorkMode, "agentic" | "plan" | "ask">,
  [string, string]
> = {
  debug: [
    "工作模式：Debug。先复现和定位根因，再做最小修复，并验证回归。",
    "Work mode: Debug. Reproduce the issue, find the root cause, make the smallest fix, and verify the regression.",
  ],
  multitask: [
    "工作模式：Multitask。拆分可独立推进的任务；只在当前环境支持时并行执行，最后整合检查。",
    "Work mode: Multitask. Split independent tasks; run them in parallel only if this environment supports it, then verify the integrated result.",
  ],
  cowork: [
    "工作模式：Cowork。与我协作推进，遇到关键选择先给出具体建议和理由，继续完成不依赖该选择的工作。",
    "Work mode: Cowork. Collaborate with me; surface consequential choices with a concrete recommendation while continuing independent work.",
  ],
  computer_use: [
    "工作模式：Computer Use。优先通过当前可用的设备、浏览器或桌面工具操作并核对实际界面；没有对应权限时说明限制。",
    "Work mode: Computer Use. Use available device, browser, or desktop tools and inspect the actual UI; explain any missing access.",
  ],
  deep_research: [
    "工作模式：Deep Research。先查证可靠来源，比较证据并标注出处，区分事实与推断。",
    "Work mode: Deep Research. Check reliable sources, compare evidence, cite sources, and distinguish facts from inference.",
  ],
  team: [
    "工作模式：Team。如当前专家具备团队能力，明确分工并整合结果；否则说明可用能力后独立完成。",
    "Work mode: Team. If this expert has team capability, assign clear roles and integrate results; otherwise explain available capability and proceed independently.",
  ],
};

/** A visible user instruction keeps the workflow request auditable in chat history. */
export function applyWorkMode(
  text: string,
  mode: WorkMode,
  language: string,
): string {
  if (mode === "agentic" || mode === "plan" || mode === "ask") return text;
  const instruction = INSTRUCTIONS[mode][language.startsWith("zh") ? 0 : 1];
  if (text.startsWith(`${instruction}\n\n`)) return text;
  return `${instruction}\n\n${text}`;
}
