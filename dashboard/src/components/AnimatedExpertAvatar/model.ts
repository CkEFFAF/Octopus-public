export const EXPERT_CHARACTERS = [
  "swallow",
  "fox",
  "owl",
  "rabbit",
  "beaver",
  "cat",
  "redpanda",
  "penguin",
  "corgi",
  "raccoon",
] as const;
export type ExpertCharacter = (typeof EXPERT_CHARACTERS)[number];
export const EXPERT_PHASES = [
  "idle",
  "welcome",
  "listening",
  "speaking",
  "thinking",
  "planning",
  "searching",
  "reading",
  "writing",
  "coding",
  "drawing",
  "analyzing",
  "running",
  "verifying",
  "collaborating",
  "handoff",
  "uploading",
  "downloading",
  "waiting_user",
  "waiting_permission",
  "paused",
  "recovering",
  "success",
  "error",
  "warning",
  "reminder",
  "offline",
  "resting",
] as const;
export type ExpertPhase = (typeof EXPERT_PHASES)[number];
export interface AnimationClip {
  frames: number[];
  holds: number[];
  loop: boolean;
}
const clips: Record<string, AnimationClip> = {
  idle: { frames: [0, 1, 0], holds: [3700, 420, 800], loop: true },
  welcome: { frames: [2, 3, 2], holds: [650, 650, 900], loop: true },
  listening: { frames: [4, 5], holds: [1800, 1800], loop: true },
  speaking: { frames: [6, 7], holds: [750, 800], loop: true },
  thinking: { frames: [8, 9, 8], holds: [2200, 450, 900], loop: true },
  reading: { frames: [10, 11], holds: [2100, 1200], loop: true },
  writing: { frames: [12, 13], holds: [850, 850], loop: true },
  coding: { frames: [14, 15], holds: [750, 750], loop: true },
  searching: { frames: [16], holds: [2800], loop: true },
  analyzing: { frames: [17], holds: [2600], loop: true },
  planning: { frames: [18], holds: [2600], loop: true },
  running: { frames: [19], holds: [2400], loop: true },
  waiting_permission: { frames: [20], holds: [5000], loop: false },
  handoff: { frames: [21], holds: [2200], loop: true },
  success: { frames: [22], holds: [1700], loop: false },
  error: { frames: [23], holds: [2200], loop: false },
};
const aliases: Partial<Record<ExpertPhase, string>> = {
  drawing: "writing",
  verifying: "planning",
  collaborating: "speaking",
  uploading: "handoff",
  downloading: "handoff",
  waiting_user: "listening",
  recovering: "running",
  warning: "error",
  reminder: "welcome",
  offline: "error",
};
export function animationClip(
  phase: ExpertPhase,
  species: ExpertCharacter,
): AnimationClip {
  if (phase === "resting") return { frames: [1], holds: [5000], loop: false };
  if (phase === "paused") return { frames: [0], holds: [5000], loop: false };
  const key = aliases[phase] ?? phase;
  const clip = clips[key] ?? clips.idle;
  if (species === "rabbit" && (key === "handoff" || key === "success"))
    return {
      ...clip,
      frames: clip.frames.map((f) => (f === 21 ? 22 : f === 22 ? 21 : f)),
    };
  if (species === "redpanda" && key === "coding")
    return { frames: [14], holds: [850], loop: true };
  return clip;
}
export function characterUrl(species: ExpertCharacter): string {
  return `/expert-animations/${species}.webp`;
}
const builtinCharacters: Record<string, ExpertCharacter> = {
  default: "swallow",
  "general-assistant": "swallow",
  "multi-agent-orchestrator": "swallow",
  "scene-default": "swallow",
  "ai-coding-coach": "fox",
  "superpowers-methodology": "fox",
  "scene-tech": "fox",
  "scene-data": "fox",
  "karpathy-knowledge-base": "owl",
  "scene-education": "redpanda",
  "scene-academic": "cat",
  "scene-content-creation": "cat",
  "scene-design": "rabbit",
  "scene-healthcare": "rabbit",
  "parenting-companion": "rabbit",
  "clinical-learning-subscription": "owl",
  "scene-legal": "owl",
  "ai-safety-guardian": "owl",
  "ops-engineer": "beaver",
  "cvm-ai-doctor": "raccoon",
  "cvm-cluster-doctor": "raccoon",
  "tencentcloud-api": "beaver",
  "office-automation": "penguin",
  "scene-office": "penguin",
  "scene-hr": "penguin",
  "wechat-ops": "penguin",
  "stock-assistant": "beaver",
  "scene-finance": "beaver",
  "scene-ecommerce": "corgi",
  "meituan-living-assistant": "corgi",
  "scene-lifestyle": "corgi",
  "scene-marketing": "fox",
  "scene-media": "cat",
  "news-trend": "owl",
  "scene-mysticism": "cat",
};
export function resolveCharacter(
  iconUrl?: string | null,
): ExpertCharacter | null {
  const url = iconUrl?.trim() ?? "";
  const selected = /^\/expert-animations\/([a-z]+)\.webp(?:\?.*)?$/.exec(
    url,
  )?.[1];
  if (selected && EXPERT_CHARACTERS.includes(selected as ExpertCharacter))
    return selected as ExpertCharacter;
  const builtin = /^\/experts\/avatars\/([a-z0-9-]+)\.svg(?:\?.*)?$/.exec(
    url,
  )?.[1];
  return builtin ? builtinCharacters[builtin] ?? null : null;
}
export function lifecyclePhase(state?: string, offline = false): ExpertPhase {
  if (offline) return "offline";
  if (state === "failed") return "error";
  if (state === "starting") return "recovering";
  if (state === "stopping") return "paused";
  if (state === "stopped" || state === "created") return "resting";
  return "idle";
}
