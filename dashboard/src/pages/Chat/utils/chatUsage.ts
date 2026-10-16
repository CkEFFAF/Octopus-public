import type { ChatMessage } from "../hooks/useChat";

export function formatTokenUsage(
  usage: ChatMessage["usage"],
  labels: { input: string; output: string; total: string; cacheHit: string },
): string[] {
  if (!usage) return [];
  const parts: string[] = [];
  if (typeof usage.input_tokens === "number")
    parts.push(`${usage.input_tokens} ${labels.input}`);
  if (
    typeof usage.cache_read_tokens === "number" &&
    usage.cache_read_tokens > 0
  ) {
    const percent =
      typeof usage.input_tokens === "number" && usage.input_tokens > 0
        ? ` (${Math.round(
            (usage.cache_read_tokens / usage.input_tokens) * 100,
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
  for (const message of messages) {
    if (message.role !== "assistant" || !message.usage || seen.has(message.id))
      continue;
    seen.add(message.id);
    result ??= {
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      total_tokens: 0,
    };
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
  return result;
}
