import {
  createContext,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import {
  octopThreadsApi,
  type SidebarStatus,
} from "../../../api/modules/octopThreads";
import type { OctopAgent } from "../../../context/AgentContext";
import { useCurrentUser } from "../../../hooks/useCurrentUser";
import * as chatStore from "./chatStore";
import { sortSessions, toSession, type Session } from "./useSessions";

const ActivityContext = createContext<Record<string, SidebarStatus>>({});

/** One lightweight request per expert, never a request per conversation. */
export function SidebarActivityProvider({
  agents,
  children,
}: {
  agents: OctopAgent[];
  children: ReactNode;
}) {
  const user = useCurrentUser();
  const ids = agents
    .map((a) => a.agent_id)
    .sort()
    .join(",");
  const scope = `${user?.id ?? ""}:${ids}`;
  const [state, setState] = useState<{
    scope: string;
    values: Record<string, SidebarStatus>;
  }>({
    scope: "",
    values: {},
  });
  useEffect(() => {
    let disposed = false;
    let inflight = false;
    const refresh = async () => {
      if (document.hidden || inflight || !ids) return;
      inflight = true;
      const entries = await Promise.all(
        ids.split(",").map(async (id) => {
          try {
            return [id, await octopThreadsApi.sidebarStatus(id)] as const;
          } catch {
            return [id, null] as const;
          }
        }),
      );
      inflight = false;
      if (disposed || entries.every(([, value]) => value === null)) return;
      setState((previous) => ({
        scope,
        values: Object.fromEntries(
          entries.map(([id, value]) => [
            id,
            value ??
              (previous.scope === scope ? previous.values[id] : undefined) ?? {
                working_threads: [],
                schedules: [],
              },
          ]),
        ),
      }));
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    const onVisible = () => {
      void refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    const unsubscribe = chatStore.onSessionEvent(() => void refresh());
    return () => {
      disposed = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      unsubscribe();
    };
  }, [ids, scope]);
  return (
    <ActivityContext.Provider value={state.scope === scope ? state.values : {}}>
      {children}
    </ActivityContext.Provider>
  );
}

export function useSidebarActivity() {
  return useContext(ActivityContext);
}

export function useSessionActivity(threadId: string) {
  const values = useSidebarActivity();
  // Subscribe only to turn boundaries. Token chunks must not rerender the sidebar.
  const streaming = useSyncExternalStore(
    (listener) =>
      chatStore.onStreamEvent((event) => {
        if (event.sessionId === threadId) listener();
      }),
    () => chatStore.getSnapshot(threadId).isStreaming,
  );
  return {
    agentId: Object.entries(values).find(([, value]) =>
      value.schedules.some((row) => row.thread_id === threadId),
    )?.[0],
    working:
      streaming ||
      Object.values(values).some((value) =>
        value.working_threads.some((row) => row.thread_id === threadId),
      ),
    schedules: Object.values(values).flatMap((value) =>
      value.schedules.filter((row) => row.thread_id === threadId),
    ),
  };
}

/** Keep older background turns visible even outside the ten recent previews. */
export function withWorkingSessions(
  sessions: Session[],
  status?: SidebarStatus,
): Session[] {
  const ids = new Set(sessions.map((session) => session.id));
  const extra = (status?.working_threads ?? []).filter(
    (row) => !ids.has(row.thread_id),
  );
  return extra.length
    ? sortSessions([...sessions, ...extra.map(toSession)])
    : sessions;
}
