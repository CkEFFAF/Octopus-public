import { useEffect, useState } from "react";
import {
  listAgentSubagents,
  type AgentSubagentSummary,
} from "../../../api/modules/subagents";
import { onToolEvent, onStreamEvent } from "./chatStore";

/** Installed workspace subagents for the running chat agent (empty if not ready). */
export function useChatSubagents(
  agentId: string | null,
): AgentSubagentSummary[] {
  const [subagents, setSubagents] = useState<AgentSubagentSummary[]>([]);

  useEffect(() => {
    if (!agentId) {
      setSubagents([]);
      return;
    }
    let cancelled = false;
    let version = 0;
    const load = () => {
      const requestVersion = ++version;
      void listAgentSubagents(agentId)
        .then((rows) => {
          if (!cancelled && requestVersion === version) setSubagents(rows);
        })
        .catch(() => {
          if (!cancelled && requestVersion === version) setSubagents([]);
        });
    };
    load();
    const offTool = onToolEvent((event) => {
      if (
        event.kind === "toolDone" &&
        /^octop_subagent_(save|install)$/.test(event.toolName)
      )
        load();
    });
    // A native write may defer graph reload until the current turn drains.
    const offStream = onStreamEvent((event) => {
      if (event.kind === "streamEnd") load();
    });
    return () => {
      cancelled = true;
      offTool();
      offStream();
    };
  }, [agentId]);

  return subagents;
}
