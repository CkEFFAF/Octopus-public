import { request, requestBlob } from "../request";
import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";

export interface CollaborationTarget {
  device_id?: string | null;
  device_name?: string;
  target_kind?: string;
  working_dir?: string | null;
  context_id?: string;
  work_mode?: string;
}

export interface CollaborationInvocation {
  invocation_id: string;
  source_agent_id: string;
  callee_agent_id: string;
  source_thread_id: string;
  child_thread_id: string | null;
  root_run_id: string;
  parent_invocation_id: string | null;
  retry_of: string | null;
  transport_status:
    | "accepted"
    | "running"
    | "completed"
    | "failed"
    | "cancelled"
    | "unknown";
  task_outcome: "unknown" | "succeeded" | "blocked" | "failed" | "needs_input";
  task_result?: {
    summary: string;
    provenance: "expert_reported";
    resources: { resource_id: string; version: string }[];
    reply: { thread_id: string; seq: number; message_id: string | null };
  } | null;
  reply_received?: boolean;
  task_result_reason?: string | null;
  target_policy: string;
  requested_target: CollaborationTarget;
  resolved_target: CollaborationTarget | null;
  error_code: string | null;
  retryable: boolean;
  prompt: string;
  created_at: number;
  updated_at: number;
}

export interface CollaborationResource {
  resource_id: string;
  version: string;
  name: string;
  media_type: string;
  size: number;
  source_agent_id: string;
  source_thread_id: string | null;
  source_kind: string;
  source_device_id: string | null;
  parse_state: string;
  publication_state: string;
  delivery_status?: "running" | "completed" | "failed" | null;
  error_code?: string | null;
  content_url: string;
  download_url: string;
  created_at: number;
}

export interface CollaborationEvent {
  seq: number;
  event_id: string;
  event_type: string;
  invocation_id: string | null;
  resource_id: string | null;
  payload: Record<string, unknown>;
  created_at: number;
}

export interface CollaborationPage {
  invocations: CollaborationInvocation[];
  events: CollaborationEvent[];
  artifacts: CollaborationResource[];
  next_cursor: number;
  has_more: boolean;
}

export interface CollaborationMessage {
  seq: number;
  role: string;
  content: unknown;
  created_at: number;
}

export interface CollaborationDetail {
  invocation: CollaborationInvocation;
  messages: CollaborationMessage[];
  has_more: boolean;
  next_before: number | null;
}

function base(agentId: string, threadId: string) {
  return `/agents/${encodeURIComponent(agentId)}/threads/${encodeURIComponent(
    threadId,
  )}`;
}

export const collaborationApi = {
  list: (agentId: string, threadId: string, after = 0) =>
    request<CollaborationPage>(
      `${base(agentId, threadId)}/collaboration?after=${after}&limit=100`,
    ),
  detail: (
    agentId: string,
    threadId: string,
    invocationId: string,
    before?: number,
  ) =>
    request<CollaborationDetail>(
      `${base(agentId, threadId)}/collaboration/${encodeURIComponent(
        invocationId,
      )}?limit=40${before == null ? "" : `&before_seq=${before}`}`,
    ),
  resource: (agentId: string, threadId: string, resourceId: string) =>
    request<CollaborationResource>(
      `${base(agentId, threadId)}/resources/${encodeURIComponent(resourceId)}`,
    ),
  content: (
    agentId: string,
    threadId: string,
    resourceId: string,
    download = false,
  ) =>
    requestBlob(
      `${base(agentId, threadId)}/resources/${encodeURIComponent(
        resourceId,
      )}/content${download ? "?download=true" : ""}`,
    ),
};

export async function downloadCollaborationResource(
  agentId: string,
  threadId: string,
  resource: CollaborationResource,
) {
  const blob = await verifiedResourceContent(agentId, threadId, resource, true);
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = resource.name;
    link.click();
  } finally {
    URL.revokeObjectURL(url);
  }
}

export async function verifiedResourceContent(
  agentId: string,
  threadId: string,
  resource: CollaborationResource,
  download = false,
) {
  const blob = await collaborationApi.content(
    agentId,
    threadId,
    resource.resource_id,
    download,
  );
  const hash = bytesToHex(sha256(new Uint8Array(await blob.arrayBuffer())));
  if (blob.size !== resource.size || hash !== resource.version)
    throw new Error("resource_version_mismatch");
  return blob;
}
