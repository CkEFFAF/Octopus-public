import { useCallback, useMemo, useSyncExternalStore } from "react";
import { useCurrentUser } from "../../../hooks/useCurrentUser";

const event = "octop:expert-order";
const fallback = new Map<string, string>();
function subscribe(listener: () => void) {
  window.addEventListener(event, listener);
  window.addEventListener("storage", listener);
  return () => {
    window.removeEventListener(event, listener);
    window.removeEventListener("storage", listener);
  };
}
function read(key: string) {
  if (fallback.has(key)) return fallback.get(key)!;
  try {
    return localStorage.getItem(key) ?? fallback.get(key) ?? "[]";
  } catch {
    return fallback.get(key) ?? "[]";
  }
}
function parse(raw: string): string[] {
  try {
    const value: unknown = JSON.parse(raw);
    return Array.isArray(value)
      ? value.filter((id): id is string => typeof id === "string")
      : [];
  } catch {
    return [];
  }
}
export function moveExpertBefore(
  ids: string[],
  source: string,
  target?: string,
) {
  if (source === target) return ids;
  const next = ids.filter((id) => id !== source);
  const index = target ? next.indexOf(target) : -1;
  next.splice(index < 0 ? next.length : index, 0, source);
  return next;
}
export function useExpertOrder() {
  const userId = useCurrentUser()?.id ?? "anonymous";
  const key = `octop:expert-order:${userId}`;
  const snapshot = useCallback(() => read(key), [key]);
  const raw = useSyncExternalStore(subscribe, snapshot, snapshot);
  const ids = useMemo(() => parse(raw), [raw]);
  const order = useCallback(
    <T extends { agent_id: string }>(items: T[]) =>
      [...items].sort((a, b) => {
        const left = ids.indexOf(a.agent_id),
          right = ids.indexOf(b.agent_id);
        return (
          (left < 0 ? ids.length : left) - (right < 0 ? ids.length : right)
        );
      }),
    [ids],
  );
  const move = useCallback(
    (available: string[], source: string, target?: string) => {
      const all = [
        ...ids.filter((id) => available.includes(id)),
        ...available.filter((id) => !ids.includes(id)),
      ];
      const value = JSON.stringify(moveExpertBefore(all, source, target));
      try {
        localStorage.setItem(key, value);
        fallback.delete(key);
      } catch {
        fallback.set(key, value);
      }
      window.dispatchEvent(new Event(event));
    },
    [ids, key],
  );
  return { order, move };
}
