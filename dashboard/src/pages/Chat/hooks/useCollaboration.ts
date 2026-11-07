import {
  createContext,
  createElement,
  useContext,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
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
function useCollaborationState(
  agentId: string,
  threadId: string,
  enabled = true,
) {
  const [page, setPage] = useState(empty);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const cursor = useRef(0);
  const busy = useRef(false);
  const mounted = useRef(false);
  const refresh = useCallback(async () => {
    if (!enabled || !agentId || !threadId) return;
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
  }, [agentId, threadId, enabled]);

  useEffect(() => {
    if (!enabled || !agentId || !threadId) return;
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
  }, [refresh, enabled, agentId, threadId]);
  return { page, loading, error, refresh };
}

const CollaborationContext = createContext<{
  agentId: string;
  threadId: string;
  value: ReturnType<typeof useCollaborationState>;
} | null>(null);

/** Key this provider by account/expert/thread so cursor and reads never cross chats. */
export function CollaborationProvider({
  agentId,
  threadId,
  children,
}: {
  agentId: string;
  threadId: string;
  children: ReactNode;
}) {
  const value = useCollaborationState(agentId, threadId);
  return createElement(
    CollaborationContext.Provider,
    { value: { agentId, threadId, value } },
    children,
  );
}

export function useCollaboration(agentId: string, threadId: string) {
  const shared = useContext(CollaborationContext);
  const matches = shared?.agentId === agentId && shared?.threadId === threadId;
  const fallback = useCollaborationState(agentId, threadId, !matches);
  return matches ? shared.value : fallback;
}
