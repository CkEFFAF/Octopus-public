import type { QueuedChatItem } from "../hooks/useChatMessageQueue";

// A withdrawal can finish after the user navigates to another conversation.
// Keep its full snapshot until the original composer is visited again.
const pending = new Map<string, QueuedChatItem>();
const listeners = new Map<string, Set<() => void>>();
const keyFor = (
  agent: string | null | undefined,
  thread: string | null | undefined,
) => `octop:withdrawn-draft:${JSON.stringify([agent, thread])}`;

export function saveWithdrawnDraft(
  agent: string | null | undefined,
  thread: string | null | undefined,
  item: QueuedChatItem,
): void {
  const key = keyFor(agent, thread);
  pending.set(key, item);
  try {
    sessionStorage.setItem(key, JSON.stringify(item));
  } catch {
    /* Memory fallback. */
  }
  listeners.get(key)?.forEach((notify) => notify());
}

export function subscribeWithdrawnDraft(
  agent: string | null | undefined,
  thread: string | null | undefined,
  notify: () => void,
): () => void {
  const key = keyFor(agent, thread);
  const subscribers = listeners.get(key) ?? new Set<() => void>();
  subscribers.add(notify);
  listeners.set(key, subscribers);
  return () => {
    subscribers.delete(notify);
    if (!subscribers.size) listeners.delete(key);
  };
}

export function readWithdrawnDraft(
  agent: string | null | undefined,
  thread: string | null | undefined,
): QueuedChatItem | null {
  const key = keyFor(agent, thread);
  let item = pending.get(key) ?? null;
  try {
    const stored = sessionStorage.getItem(key);
    if (!item && stored) item = JSON.parse(stored) as QueuedChatItem;
  } catch {
    /* Memory fallback. */
  }
  return item;
}

export function takeWithdrawnDraft(
  agent: string | null | undefined,
  thread: string | null | undefined,
): QueuedChatItem | null {
  const item = readWithdrawnDraft(agent, thread);
  const key = keyFor(agent, thread);
  try {
    sessionStorage.removeItem(key);
  } catch {
    /* Memory fallback. */
  }
  pending.delete(key);
  return item;
}
