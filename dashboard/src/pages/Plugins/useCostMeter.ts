import { useCallback, useEffect, useRef, useState } from "react";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import {
  pluginMarketApi,
  PLUGIN_MARKET_CHANGED,
  type CostMeterState,
} from "../../api/modules/pluginMarket";

export function useCostMeter() {
  const user = useCurrentUser();
  const userId = user?.id;
  const [snapshot, setSnapshot] = useState<{
    userId: number;
    state: CostMeterState;
  } | null>(null);
  const state = snapshot && snapshot.userId === userId ? snapshot.state : null;
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(Date.now());
  const mounted = useRef(false);
  const owner = useRef(userId);
  owner.current = userId;
  const offset = useRef(0);
  const boundaryAttempt = useRef(0);
  const refresh = useCallback(
    async (remote = false) => {
      const requestedOwner = userId;
      if (requestedOwner == null) return;
      setBusy(true);
      try {
        const result = await (remote
          ? pluginMarketApi.refresh()
          : pluginMarketApi.state());
        if (!mounted.current || owner.current !== requestedOwner) return;
        offset.current = Date.parse(result.server_time) - Date.now();
        setSnapshot({ userId: requestedOwner, state: result });
        setError(false);
      } catch {
        if (mounted.current && owner.current === requestedOwner) setError(true);
      } finally {
        if (mounted.current && owner.current === requestedOwner) setBusy(false);
      }
    },
    [userId],
  );

  useEffect(() => {
    mounted.current = true;
    setSnapshot(null);
    setError(false);
    void refresh(true);
    const clock = window.setInterval(() => setTick(Date.now()), 1000);
    const poll = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh(true);
    }, 60_000);
    const changed = () => void refresh(true);
    window.addEventListener(PLUGIN_MARKET_CHANGED, changed);
    return () => {
      mounted.current = false;
      window.clearInterval(clock);
      window.clearInterval(poll);
      window.removeEventListener(PLUGIN_MARKET_CHANGED, changed);
    };
  }, [refresh]);

  useEffect(() => {
    if (
      state &&
      Date.parse(state.peak.next_change_at) <= tick + offset.current &&
      tick - boundaryAttempt.current >= 15_000
    ) {
      boundaryAttempt.current = tick;
      void refresh();
    }
  }, [state, tick, refresh]);

  return { state, error, busy, refresh, now: tick + offset.current };
}
