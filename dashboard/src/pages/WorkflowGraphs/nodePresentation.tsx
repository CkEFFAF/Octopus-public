import {
  Bot,
  Clock3,
  Flag,
  GitBranch,
  Merge,
  Play,
  Radio,
  Split,
  Terminal,
  Timer,
} from "lucide-react";
import type { GraphNode, NodeKind } from "../../api/modules/workflowGraphs";

export const NODE_WIDTH = 272;
export const PORT_HEIGHT = 28;
export function nodePorts(
  node: GraphNode,
): ("next" | "true" | "false" | "error")[] {
  return node.kind === "end"
    ? []
    : node.kind === "condition"
    ? ["true", "false", "error"]
    : ["next", "error"];
}
export function nodeHeaderHeight(node: GraphNode) {
  return node.kind === "agent" ? 138 : 112;
}
export function NodeIcon({
  kind,
  size = 18,
}: {
  kind: NodeKind;
  size?: number;
}) {
  const Icon = {
    entry: Play,
    agent: Bot,
    script: Terminal,
    condition: GitBranch,
    event: Radio,
    wait_event: Clock3,
    wait_time: Timer,
    fork: Split,
    join: Merge,
    end: Flag,
  }[kind];
  return <Icon size={size} strokeWidth={1.8} aria-hidden="true" />;
}
export function nodePreview(
  node: GraphNode,
  tr: (key: string) => string,
): string {
  if (node.kind === "agent" && node.prompt) return String(node.prompt);
  if (node.kind === "script" && Array.isArray(node.argv) && node.argv.length)
    return node.argv.join(" ");
  if (node.kind === "event")
    return String(node.event_type || tr("nodeHint.event"));
  if (node.kind === "wait_time")
    return `${Number(node.seconds || 60)} ${tr("secondsUnit")}`;
  if (node.kind === "wait_event" && node.event_node)
    return `${tr("kind.wait_event")} / ${node.event_node}`;
  return tr(`nodeHint.${node.kind}`);
}
