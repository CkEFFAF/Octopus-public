import { useCallback, useEffect, useRef, useState } from "react";
import {
  workItemsApi,
  type WorkItemDetail,
  type WorkItemSummary,
} from "../../../api/modules/workItems";

import { WORK_ITEMS_CHANGED_EVENT } from "../../../utils/dashboardPushToast";
export { WORK_ITEMS_CHANGED_EVENT } from "../../../utils/dashboardPushToast";

export function useWorkItems(
  originThreadId: string,
  all: boolean,
  selectedId: string | null,
) {
  const key = JSON.stringify([originThreadId, all]);
  const currentKey = useRef(key);
  const listRequest = useRef(0);
  currentKey.current = key;
  const [list, setList] = useState<{
    key: string;
    items: WorkItemSummary[];
    hasMore: boolean;
  } | null>(null);
  const [detail, setDetail] = useState<WorkItemDetail | null>(null);
  const [error, setError] = useState(false);
  const refresh = useCallback(async () => {
    const requestId = ++listRequest.current;
    try {
      const data = await workItemsApi.list(all ? undefined : originThreadId);
      if (currentKey.current !== key || listRequest.current !== requestId)
        return;
      setList({ key, items: data.items, hasMore: data.has_more });
      setError(false);
    } catch {
      if (currentKey.current === key && listRequest.current === requestId)
        setError(true);
    }
  }, [originThreadId, all, key]);
  useEffect(() => {
    currentKey.current = key;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (!document.hidden) await refresh();
      if (active) timer = setTimeout(poll, 5000);
    };
    void poll();
    const recover = () => {
      if (!document.hidden) void refresh();
    };
    window.addEventListener("online", recover);
    window.addEventListener("focus", recover);
    window.addEventListener(WORK_ITEMS_CHANGED_EVENT, recover);
    document.addEventListener("visibilitychange", recover);
    return () => {
      active = false;
      currentKey.current = "";
      clearTimeout(timer);
      window.removeEventListener("online", recover);
      window.removeEventListener("focus", recover);
      window.removeEventListener(WORK_ITEMS_CHANGED_EVENT, recover);
      document.removeEventListener("visibilitychange", recover);
    };
  }, [refresh, key]);
  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    let request = 0;
    const refreshDetail = async () => {
      const requestId = ++request;
      if (!document.hidden) {
        try {
          const next = await workItemsApi.detail(selectedId);
          if (active && request === requestId) {
            setDetail(next);
            setError(false);
          }
        } catch {
          if (active && request === requestId) setError(true);
        }
      }
    };
    const poll = async () => {
      await refreshDetail();
      if (active) timer = setTimeout(poll, 2500);
    };
    void poll();
    window.addEventListener(WORK_ITEMS_CHANGED_EVENT, refreshDetail);
    window.addEventListener("online", refreshDetail);
    window.addEventListener("focus", refreshDetail);
    return () => {
      active = false;
      clearTimeout(timer);
      window.removeEventListener(WORK_ITEMS_CHANGED_EVENT, refreshDetail);
      window.removeEventListener("online", refreshDetail);
      window.removeEventListener("focus", refreshDetail);
    };
  }, [selectedId]);
  return {
    items: list?.key === key ? list.items : [],
    hasMore: list?.key === key && list.hasMore,
    detail: detail?.task_id === selectedId ? detail : null,
    error,
    refresh,
  };
}
