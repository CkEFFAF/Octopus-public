import { useEffect, useState } from "react";
import {
  executionApi,
  type RequestSnapshot,
} from "../../../api/modules/execution";
import { useCurrentUser } from "../../../hooks/useCurrentUser";
import { reportedCacheRead } from "../utils/chatUsage";

/** Current request receipts are independent of legacy message-history totals. */
export function recentCompletedRequest(requests: RequestSnapshot[]) {
  const entry = requests
    .filter((item) => item.status === "completed")
    .sort((a, b) => b.created_at - a.created_at)[0];
  if (!entry) return null;
  const usage = entry.actual_usage;
  const read = reportedCacheRead(usage);
  // Old normalized snapshots could contain a manufactured zero.
  const reported =
    read !== undefined && (usage?.cache_metrics_reported === true || read > 0);
  return {
    ...entry,
    actual_usage: usage
      ? {
          ...usage,
          cache_read_tokens: reported ? read : undefined,
          cache_metrics_reported: reported,
        }
      : null,
  };
}

export function useRecentRequestUsage(
  agentId?: string,
  threadId?: string,
  streaming = false,
) {
  const user = useCurrentUser();
  const key =
    user && agentId && threadId ? `${user.id}/${agentId}/${threadId}` : "";
  const [state, setState] = useState<{
    key: string;
    entry: ReturnType<typeof recentCompletedRequest>;
    failed: boolean;
  } | null>(null);
  useEffect(() => {
    if (!key || !agentId || !threadId) return;
    let active = true;
    let busy = false;
    const refresh = async () => {
      if (busy || document.visibilityState === "hidden") return;
      busy = true;
      try {
        let entry: ReturnType<typeof recentCompletedRequest> = null;
        let before: number | undefined;
        // Failures/cancellations must not hide the latest completed receipt.
        // Bound inspection work when a thread has an extended failure streak.
        for (let page = 0; page < 4 && active; page++) {
          const result = await executionApi.recentRequests(
            agentId,
            threadId,
            before,
          );
          entry = recentCompletedRequest(result.requests);
          if (
            entry ||
            !result.has_more ||
            result.next_before === null ||
            result.next_before === before
          )
            break;
          before = result.next_before;
        }
        if (active)
          setState({
            key,
            entry,
            failed: false,
          });
      } catch {
        if (active) setState({ key, entry: null, failed: true });
      } finally {
        busy = false;
      }
    };
    void refresh();
    const timer = streaming
      ? window.setInterval(() => void refresh(), 5000)
      : undefined;
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [key, agentId, threadId, streaming]);
  return state?.key === key
    ? { ...state, loading: false }
    : { entry: null, failed: false, loading: Boolean(key) };
}
