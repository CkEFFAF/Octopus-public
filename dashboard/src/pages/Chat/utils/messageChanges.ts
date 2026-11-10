import type { ChatMessage } from "../hooks/useChat";

type Change = { parent: number; first: number };
const identities = new WeakMap<ChatMessage[], number>();
const changes = new Map<number, Change>();
let sequence = 0;

function identity(messages: ChatMessage[]): number {
  let value = identities.get(messages);
  if (value === undefined) {
    value = ++sequence;
    identities.set(messages, value);
  }
  return value;
}

/** Hints are valid only for copy-on-write replacements of immutable messages. */
export function recordMessageChange(
  messages: ChatMessage[],
  parent: ChatMessage[],
  first: number,
): void {
  if (messages !== parent) {
    // Retain numeric ancestry only; keeping parent arrays would retain every
    // historical copy of a long conversation throughout a stream.
    changes.set(identity(messages), { parent: identity(parent), first });
    if (changes.size > 1024) changes.delete(changes.keys().next().value!);
  } else {
    const change = changes.get(identity(messages));
    if (change) change.first = Math.min(change.first, first);
  }
}

export function firstMessageChange(
  messages: ChatMessage[],
  previous: ChatMessage[],
): number | undefined {
  let first = Infinity;
  let cursor = identities.get(messages);
  const target = identities.get(previous);
  if (cursor === undefined || target === undefined) return undefined;
  // Skipped renders can span several published snapshots. Unknown ancestry
  // uses the full grouping path rather than guessing that the prefix is stable.
  for (let depth = 0; depth < 16; depth++) {
    const change = changes.get(cursor);
    if (!change) return undefined;
    first = Math.min(first, change.first);
    if (change.parent === target) return first;
    cursor = change.parent;
  }
  return undefined;
}
