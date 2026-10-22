import { useEffect, useRef, useState } from "react";
import {
  octopCronApi,
  type SchedulePage,
  type ScheduleQuery,
} from "../api/modules/cronjob";

const empty: SchedulePage = {
  items: [],
  total: 0,
  has_more: false,
  next_offset: null,
  counts: { schedules: 0, reminders: 0 },
};

export function useSchedulePage(query: ScheduleQuery) {
  const key = JSON.stringify(query);
  const [state, setState] = useState({
    key,
    page: empty,
    loading: true,
    error: "",
  });
  const [loadingMore, setLoadingMore] = useState(false);
  const refreshRef = useRef<() => Promise<void>>(async () => {});
  const moreRef = useRef<() => Promise<void>>(async () => {});
  useEffect(() => {
    let disposed = false;
    let epoch = 0;
    let loaded = 5;
    let nextOffset: number | null = null;
    let busy = false;
    let timer: ReturnType<typeof setTimeout>;
    const filters = JSON.parse(key) as ScheduleQuery;
    setState({ key, page: empty, loading: true, error: "" });
    setLoadingMore(false);
    async function refresh() {
      if (busy) return;
      const request = ++epoch;
      clearTimeout(timer);
      try {
        const page = await octopCronApi.page(filters, 0, loaded);
        if (disposed || request !== epoch) return;
        nextOffset = page.next_offset;
        setState({ key, page, loading: false, error: "" });
      } catch (error) {
        if (!disposed && request === epoch)
          setState((old) => ({ ...old, loading: false, error: String(error) }));
      } finally {
        if (!disposed && request === epoch)
          timer = setTimeout(
            () => void refresh(),
            document.hidden ? 30000 : 5000,
          );
      }
    }
    moreRef.current = async () => {
      if (busy || nextOffset === null || disposed) return;
      busy = true;
      ++epoch;
      clearTimeout(timer);
      setLoadingMore(true);
      try {
        const page = await octopCronApi.page(filters, nextOffset, 5);
        if (disposed) return;
        loaded += page.items.length;
        nextOffset = page.next_offset;
        setState((old) => ({
          key,
          loading: false,
          error: "",
          page: {
            ...page,
            items: Array.from(
              new Map(
                [...old.page.items, ...page.items].map((item) => [
                  `${item.agent_id}:${item.id}`,
                  item,
                ]),
              ).values(),
            ),
          },
        }));
      } catch (error) {
        if (!disposed) setState((old) => ({ ...old, error: String(error) }));
      } finally {
        busy = false;
        if (!disposed) {
          setLoadingMore(false);
          timer = setTimeout(() => void refresh(), 5000);
        }
      }
    };
    refreshRef.current = refresh;
    const visible = () => {
      if (!document.hidden) void refresh();
    };
    void refresh();
    document.addEventListener("visibilitychange", visible);
    return () => {
      disposed = true;
      ++epoch;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [key]);
  const valid = state.key === key;
  return {
    ...(valid ? state.page : empty),
    loading: !valid || state.loading,
    error: valid ? state.error : "",
    loadingMore: valid && loadingMore,
    loadMore: () => moreRef.current(),
    refresh: () => refreshRef.current(),
  };
}
