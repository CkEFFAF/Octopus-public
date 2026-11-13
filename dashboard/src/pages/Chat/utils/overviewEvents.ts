import type { ConversationEvent } from "../../../api/modules/conversationMetadata";

/** Fold only adjacent identical execution summaries, retaining every original. */
export function groupOverviewEvents(events: ConversationEvent[]) {
  const groups: ConversationEvent[][] = [];
  for (const event of events) {
    const last = groups.at(-1);
    const previous = last?.at(-1);
    if (
      previous &&
      event.kind === "execution" &&
      previous.kind === event.kind &&
      previous.text === event.text &&
      Math.abs(previous.occurred_at - event.occurred_at) <= 60
    ) {
      last!.push(event);
    } else groups.push([event]);
  }
  return groups;
}

export function overviewTitle(text: string) {
  return text
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/\*\*|__|`/g, "")
    .replace(/^#{1,6}\s+/g, "")
    .trim();
}
