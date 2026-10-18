import { useCallback, useEffect, useRef, useState } from "react";
import {
  collaborationApi,
  type CollaborationPage,
} from "../../../api/modules/collaboration";

const empty: CollaborationPage = {
  invocations: [],
  events: [],
  artifacts: [],
  next_cursor: 0,
  has_more: false,
};

function mergeBy<T>(old: T[], next: T[], key: (item: T) => string): T[] {
  const rows = new Map(old.map((item) => [key(item), item]));
  next.forEach((item) => rows.set(key(item), item));
  return [...rows.values()];
}

/** Mount with the thread as React key so in-flight reads cannot cross chats. */
export function useCollaboration(agentId: string, threadId: string) {
  const [page, setPage] = useState(empty);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const cursor = useRef(0);
  const busy = useRef(false);
  const mounted = useRef(false);
  const refresh = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    setLoading(true);
    try {
      const next = await collaborationApi.list(
        agentId,
        threadId,
        cursor.current,
      );
      if (!mounted.current) return;
      cursor.current = Math.max(cursor.current, next.next_cursor);
      setPage((prev) => ({
        invocations: mergeBy(
          prev.invocations,
          next.invocations,
          (item) => item.invocation_id,
        ),
        artifacts: mergeBy(
          prev.artifacts,
          next.artifacts,
          (item) => item.resource_id,
        ),
        events: mergeBy(prev.events, next.events, (item) => item.event_id)
          .sort((a, b) => a.seq - b.seq)
          .slice(-100),
        next_cursor: cursor.current,
        has_more: next.has_more,
      }));
      setError(false);
    } catch {
      if (mounted.current) setError(true);
    } finally {
      busy.current = false;
      if (mounted.current) setLoading(false);
    }
  }, [agentId, threadId]);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const recover = () => {
      if (document.visibilityState !== "hidden") void refresh();
    };
    const interval = window.setInterval(recover, 5000);
    window.addEventListener("focus", recover);
    window.addEventListener("online", recover);
    document.addEventListener("visibilitychange", recover);
    return () => {
      mounted.current = false;
      window.clearInterval(interval);
      window.removeEventListener("focus", recover);
      window.removeEventListener("online", recover);
      document.removeEventListener("visibilitychange", recover);
    };
  }, [refresh]);
  return { page, loading, error, refresh };
}
