import type { ChatMessage } from "../hooks/useChat";

/** Preserve missing provider data; an explicitly reported zero is still valid. */
export function reportedCacheRead(value: unknown): number | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value))
    return undefined;
  const raw = value as Record<string, unknown>;
  if (raw.cache_metrics_reported === false) return undefined;
  const valid = (n: unknown): n is number =>
    typeof n === "number" && Number.isFinite(n) && n >= 0;
  for (const key of ["cache_read_tokens", "prompt_cache_hit_tokens"]) {
    if (valid(raw[key])) return Math.floor(raw[key]);
  }
  const details = raw.input_token_details ?? raw.prompt_tokens_details;
  if (!details || typeof details !== "object" || Array.isArray(details))
    return undefined;
  const values = Object.entries(details).filter(
    ([key, n]) =>
      ["cache_read", "cached_tokens"].some(
        (name) => key === name || key.endsWith(`_${name}`),
      ) && valid(n),
  );
  return values.length
    ? values.reduce((total, [, n]) => total + Math.floor(n as number), 0)
    : undefined;
}

export function formatTokenUsage(
  usage: ChatMessage["usage"],
  labels: { input: string; output: string; total: string; cacheHit: string },
): string[] {
  if (!usage) return [];
  const parts: string[] = [];
  if (typeof usage.input_tokens === "number")
    parts.push(`${usage.input_tokens} ${labels.input}`);
  if (
    reportedCacheRead(usage) !== undefined &&
    (usage.cache_read_tokens ?? 0) > 0
  ) {
    const percent =
      typeof usage.input_tokens === "number" && usage.input_tokens > 0
        ? ` (${Math.round(
            ((usage.cache_read_tokens ?? 0) / usage.input_tokens) * 100,
          )}%)`
        : "";
    parts.push(`${usage.cache_read_tokens} ${labels.cacheHit}${percent}`);
  }
  if (typeof usage.output_tokens === "number")
    parts.push(`${usage.output_tokens} ${labels.output}`);
  if (typeof usage.total_tokens === "number")
    parts.push(`${usage.total_tokens} ${labels.total}`);
  return parts;
}

/** Input is the existing normalized turn projection: per-call samples are already rolled up once. */
export function sumVisibleTurnUsage(
  messages: ChatMessage[],
): ChatMessage["usage"] {
  const seen = new Set<string>();
  let result: NonNullable<ChatMessage["usage"]> | undefined;
  let cacheComplete = true;
  for (const message of messages) {
    if (message.role !== "assistant" || !message.usage || seen.has(message.id))
      continue;
    seen.add(message.id);
    result ??= {
      input_tokens: 0,
      output_tokens: 0,
      total_tokens: 0,
    };
    const cache = reportedCacheRead(message.usage);
    if (
      typeof cache !== "number" ||
      !Number.isFinite(cache) ||
      cache < 0 ||
      typeof message.usage.input_tokens !== "number"
    )
      cacheComplete = false;
    for (const key of [
      "input_tokens",
      "output_tokens",
      "cache_read_tokens",
      "total_tokens",
    ] as const) {
      const value = message.usage[key];
      if (typeof value === "number" && Number.isFinite(value) && value >= 0)
        result[key] = (result[key] ?? 0) + value;
    }
  }
  if (result && !cacheComplete) delete result.cache_read_tokens;
  return result;
}
