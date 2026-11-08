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
  "panda",
  "koala",
  "otter",
  "dragon",
  "bunny",
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
export const GIF_CLIPS = [
  "idle",
  "thinking",
  "working",
  "reading",
  "handoff",
  "waiting",
  "success",
  "error",
] as const;
export type GifClip = (typeof GIF_CLIPS)[number];
const phaseClips: Record<ExpertPhase, GifClip> = {
  idle: "idle",
  welcome: "success",
  listening: "idle",
  speaking: "handoff",
  thinking: "thinking",
  planning: "thinking",
  searching: "reading",
  reading: "reading",
  writing: "working",
  coding: "working",
  drawing: "working",
  analyzing: "thinking",
  running: "working",
  verifying: "reading",
  collaborating: "handoff",
  handoff: "handoff",
  uploading: "handoff",
  downloading: "handoff",
  waiting_user: "waiting",
  waiting_permission: "waiting",
  paused: "idle",
  recovering: "working",
  success: "success",
  error: "error",
  warning: "error",
  reminder: "waiting",
  offline: "error",
  resting: "idle",
};
export function gifClip(phase: ExpertPhase): GifClip {
  return phaseClips[phase];
}
export function animationUrl(
  species: ExpertCharacter,
  phase: ExpertPhase,
  moving = true,
): string {
  return `/expert-animations/v2/${species}/${gifClip(phase)}.${
    moving ? "gif" : "png"
  }`;
}
/** Stable stored identity, also supported by native management tools. */
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
  const gifSelected =
    /^\/expert-animations\/v2\/([a-z]+)\/[a-z]+\.(?:gif|png)(?:\?.*)?$/.exec(
      url,
    )?.[1];
  if (gifSelected && EXPERT_CHARACTERS.includes(gifSelected as ExpertCharacter))
    return gifSelected as ExpertCharacter;
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
