export type ConversationCategory = "user" | "agent_collaboration";

export interface ConversationActor {
  kind: string;
  id: string;
  name: string;
}

export interface CollaborationSource {
  kind: string;
  parent_thread_id?: string | null;
  runner_name?: string | null;
  acp_session_id?: string | null;
  device_id?: string | null;
}

export interface ConversationOrigin {
  category?: ConversationCategory;
  actor?: ConversationActor | null;
  collaboration_source?: CollaborationSource | null;
}

export function parseConversationActor(
  value: unknown,
): ConversationActor | undefined {
  if (!value || typeof value !== "object") return undefined;
  const actor = value as Record<string, unknown>;
  if (
    typeof actor.kind !== "string" ||
    typeof actor.id !== "string" ||
    typeof actor.name !== "string" ||
    !actor.name.trim()
  )
    return undefined;
  return { kind: actor.kind, id: actor.id, name: actor.name };
}
