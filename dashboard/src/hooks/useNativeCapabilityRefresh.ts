import { useEffect } from "react";
import { onToolEvent } from "../pages/Chat/hooks/chatStore";

/** Refresh open skill/tool panels after successful native configuration writes. */
export function useNativeCapabilityRefresh(
  agentId: string | null,
  resource: "skills" | "tools",
  refresh: () => Promise<unknown>,
) {
  useEffect(() => {
    if (!agentId) return;
    return onToolEvent((event) => {
      if (event.kind !== "toolDone" || !event.result) return;
      const relevant =
        resource === "skills"
          ? /^octop_(skill|plugin|expert)_(save|install|set_enabled|update)$/
          : /^octop_(tool|plugin|expert)_(install|set_enabled|update)$/;
      if (!relevant.test(event.toolName)) return;
      try {
        const result = JSON.parse(event.result) as Record<
          string,
          unknown
        > | null;
        if (result?.saved !== true) return;
        if (
          result.agent_id !== agentId &&
          event.toolName !== "octop_plugin_install"
        )
          return;
        void refresh();
      } catch {
        // Plain text and incomplete tool output are not save receipts.
      }
    });
  }, [agentId, resource, refresh]);
}
