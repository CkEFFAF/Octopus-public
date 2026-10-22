import { useCallback, useMemo, useSyncExternalStore } from "react";
import { useCurrentUser } from "../../../hooks/useCurrentUser";

const EVENT = "octop:pinned-experts-changed";
const memory = new Map<string, string>();

function subscribe(listener: () => void) {
  window.addEventListener(EVENT, listener);
  window.addEventListener("storage", listener);
  return () => {
    window.removeEventListener(EVENT, listener);
    window.removeEventListener("storage", listener);
  };
}

function read(key: string): string {
  if (memory.has(key)) return memory.get(key)!;
  try {
    return localStorage.getItem(key) ?? "[]";
  } catch {
    return memory.get(key) ?? "[]";
  }
}

function parse(raw: string): string[] {
  try {
    const value: unknown = JSON.parse(raw);
    return Array.isArray(value)
      ? [
          ...new Set(
            value.filter((id): id is string => typeof id === "string" && !!id),
          ),
        ]
      : [];
  } catch {
    return [];
  }
}

/** Browser preference scoped to the signed-in account, shared by both sidebar modes. */
export function usePinnedExperts() {
  const userId = useCurrentUser()?.id ?? "anonymous";
  const key = `octop:pinned-experts:${userId}`;
  const snapshot = useCallback(() => read(key), [key]);
  const raw = useSyncExternalStore(subscribe, snapshot, snapshot);
  const pinnedIds = useMemo(() => parse(raw), [raw]);
  const togglePin = useCallback(
    (agentId: string) => {
      const ids = parse(read(key));
      const next = ids.includes(agentId)
        ? ids.filter((id) => id !== agentId)
        : [...ids, agentId];
      const value = JSON.stringify(next);
      try {
        localStorage.setItem(key, value);
        memory.delete(key);
      } catch {
        // Retain the preference for this tab when storage is unavailable.
        memory.set(key, value);
      }
      window.dispatchEvent(new Event(EVENT));
    },
    [key],
  );
  return { pinnedIds, togglePin };
}
