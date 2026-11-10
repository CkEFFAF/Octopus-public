import type {
  CollaborationPage,
  CollaborationResource,
} from "../../../api/modules/collaboration";
import type { ChatMessage } from "../hooks/useChat";
import type { MessageGroup } from "./messageGrouping";

const references = new WeakMap<ChatMessage, string[]>();
function resourceReferences(message: ChatMessage): string[] {
  const cached = references.get(message);
  if (cached) return cached;
  const ids = new Set<string>();
  const addUrl = (url?: string) => {
    const id = url?.match(/\/resources\/([^/?#]+)\/content(?:[?#]|$)/)?.[1];
    if (id) ids.add(id);
  };
  for (const item of message.attachments ?? []) {
    if (item.resourceId) ids.add(item.resourceId);
    addUrl(item.url);
  }
  if (
    !message.toolData?.errorCode &&
    message.status !== "error" &&
    !message.errorInfo &&
    ["publish_artifact", "send_file", "send_file_to_user"].includes(
      message.toolData?.name?.split("/").pop() ?? "",
    )
  ) {
    try {
      const output = JSON.parse(message.toolData?.output ?? "null");
      if (
        output &&
        output.status !== "failed" &&
        !output.is_error &&
        !output.error &&
        typeof output.resource_id === "string"
      )
        ids.add(output.resource_id);
    } catch {
      /* Legacy media records use the publication time fallback. */
    }
  }
  const result = [...ids];
  references.set(message, result);
  return result;
}

/** Authorized resources remain attached to their original assistant answer.
 * Explicit publication references win; legacy records use only the source
 * expert and the original user-turn time interval, never the latest answer.
 */
export function turnDeliverables(
  groups: MessageGroup[],
  page: CollaborationPage,
  agentId: string,
  threadId: string,
) {
  const result = new Map<string, CollaborationResource[]>();
  if (page.artifacts.length === 0) return result;
  const turns: {
    key: string;
    speaker: string;
    start: number;
    end: number;
    latest: number;
    refs: Set<string>;
  }[] = [];
  let start = -Infinity;
  let round: typeof turns = [];
  for (const group of groups) {
    const user = group.messages.find((message) => message.role === "user");
    if (user) {
      for (const turn of round) turn.end = user.timestamp;
      round = [];
      start = user.timestamp;
      continue;
    }
    const assistant = group.messages.find(
      (message) => message.role === "assistant",
    );
    if (!assistant) continue;
    const turn = {
      key: group.messages[0].id,
      speaker: assistant.speakerAgentId || agentId,
      start: Number.isFinite(start)
        ? start
        : Math.min(...group.messages.map((message) => message.timestamp)),
      end: Infinity,
      latest: Math.max(...group.messages.map((message) => message.timestamp)),
      refs: new Set(group.messages.flatMap(resourceReferences)),
    };
    turns.push(turn);
    round.push(turn);
  }
  const explicitTargets = new Map<string, typeof turns>();
  const bySpeaker = new Map<string, typeof turns>();
  for (const turn of turns) {
    for (const id of turn.refs) {
      const targets = explicitTargets.get(id) ?? [];
      targets.push(turn);
      explicitTargets.set(id, targets);
    }
    const speakerTurns = bySpeaker.get(turn.speaker) ?? [];
    speakerTurns.push(turn);
    bySpeaker.set(turn.speaker, speakerTurns);
  }
  const invocations = new Map<
    string,
    CollaborationPage["invocations"][number]
  >();
  for (const invocation of page.invocations) {
    for (const ref of invocation.task_result?.resources ?? []) {
      const key = JSON.stringify([ref.resource_id, ref.version]);
      if (!invocations.has(key)) invocations.set(key, invocation);
    }
  }
  const place = (speaker: string, time: number) => {
    const candidates = (bySpeaker.get(speaker) ?? []).filter(
      (turn) =>
        turn.speaker === speaker && turn.start <= time && time < turn.end,
    );
    return candidates.find((turn) => turn.latest >= time) ?? candidates.at(-1);
  };
  for (const resource of page.artifacts) {
    if (
      resource.source_kind === "upload" ||
      resource.publication_state !== "published"
    )
      continue;
    let targets = explicitTargets.get(resource.resource_id) ?? [];
    if (targets.length === 0) {
      const invocation = invocations.get(
        JSON.stringify([resource.resource_id, resource.version]),
      );
      const turn = invocation
        ? place(invocation.source_agent_id, invocation.created_at * 1000)
        : resource.source_thread_id === threadId
        ? place(resource.source_agent_id, resource.created_at * 1000)
        : undefined;
      if (turn) targets = [turn];
    }
    for (const turn of targets) {
      const files = result.get(turn.key) ?? [];
      files.push(resource);
      result.set(turn.key, files);
    }
  }
  return result;
}
