import type { ChatMessage } from "../hooks/useChat";

export interface ScheduleMessageAnchor {
  threadId: string;
  after: number;
  before?: number;
  excerpt: string;
}

/** Resolve the public result within its actual execution, never a same-text older run. */
export function findScheduleMessage(
  messages: ChatMessage[],
  anchor: ScheduleMessageAnchor,
) {
  const normalize = (text: string) => text.replace(/\s+/g, " ").trim();
  const excerpt = normalize(anchor.excerpt).slice(0, 180);
  return messages.find(
    (message) =>
      message.role === (excerpt ? "assistant" : "user") &&
      message.timestamp >= anchor.after - 1000 &&
      (anchor.before == null || message.timestamp <= anchor.before + 1000) &&
      (!excerpt || normalize(message.content).includes(excerpt)),
  );
}
