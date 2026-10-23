import { request } from "../request";

export interface MetadataSettings {
  revision: number;
  title_enabled: boolean;
  brief_enabled: boolean;
  title_model: string;
  brief_model: string;
}
export interface MetadataSettingsView extends MetadataSettings {
  models: { value: string; label: string }[];
  resolved_title_model: string | null;
  resolved_brief_model: string | null;
  title_available: boolean;
  brief_available: boolean;
}
export interface ConversationSourceRef {
  kind: string;
  id: string;
  revision?: number | null;
}
export interface BriefItem {
  text: string;
  source_refs: ConversationSourceRef[];
}
export interface Coverage {
  message_seq: number;
  message_offset: number;
  archive_seq: number;
  archive_offset: number;
  event_seq: number;
  complete: boolean;
  history_status: string;
  truncated_sources: boolean;
}
export interface ConversationBrief {
  thread_id: string;
  revision: number;
  objective_version: number;
  title: string | null;
  title_source: string;
  title_revision: number;
  suggested_title: string | null;
  overview: {
    one_liner: string;
    objective: string;
    scope: string;
    constraints: BriefItem[];
  };
  progress: {
    stage: string;
    execution_state: string;
    work_state: string;
    display_state: string;
    observation: string;
    truncated?: boolean;
    completed: BriefItem[];
    in_progress: BriefItem[];
    remaining: BriefItem[];
    blockers: BriefItem[];
    next_actions: BriefItem[];
    reported_plan_completed: number;
    plan_total: number;
    verification_passed?: number;
    verification_reported?: number;
    verification?: {
      status: string;
      receipt_backed: boolean;
      source_refs: ConversationSourceRef[];
    }[];
    acceptance: { actor: number; at: number } | null;
  };
  decisions: BriefItem[];
  findings: BriefItem[];
  artifact_refs: { path: string; agent_id?: string }[];
  manual_overrides: { objective?: string; scope?: string; note?: string };
  provenance: {
    freshness: string;
    generated_at: number;
    effective_model_ref: string | null;
    source_revision: number;
    coverage: Coverage;
    last_error: string;
    diagnostic?: Record<string, unknown>;
  };
}
export interface MetadataJob {
  job_id: string;
  kind: string;
  status: string;
  attempts: number;
  error_code: string;
  result: {
    diagnostic?: Record<string, unknown>;
    suggested_title?: string;
    title_revision?: number;
    digest_id?: string;
  };
  updated_at: number;
}
export interface ConversationEvent {
  event_id: string;
  kind: string;
  text: string;
  occurred_at: number;
  recorded_at: number;
  source_refs: ConversationSourceRef[];
  author_kind: string;
  details: Record<string, unknown>;
}
export interface ConversationEventPage {
  events: ConversationEvent[];
  next_cursor: string | null;
  from_ts: number;
  to_ts: number;
  timezone: string;
  coverage: Coverage;
}
export interface ConversationDigest {
  digest_id: string;
  window: string;
  from_ts: number;
  to_ts: number;
  summary: string;
  event_ids: string[];
  coverage: Coverage;
  source_revision: number;
  generated_at: number;
  effective_model_ref: string | null;
  freshness: string;
}
export interface ConversationSource {
  kind: string;
  id: string;
  text: string;
  details: Record<string, unknown>;
}
export interface HistoryBatch {
  recovered?: number;
  started_at?: number;
  updated_at?: number;
  finished_at?: number;
  failures?: Array<{
    job_id: string;
    thread_id: string;
    code: string;
    diagnostic: Record<string, unknown>;
  }>;
  batch_id: string;
  errors?: Record<string, number>;
  total: number;
  queued: number;
  running: number;
  ready: number;
  failed: number;
  cancelled: number;
}
export type OrganizationAge =
  | "all"
  | "never"
  | "d1"
  | "d3"
  | "d5"
  | "d7"
  | "older";
export type OrganizationStatus =
  | "all"
  | "never"
  | "active"
  | "ready"
  | "failed"
  | "cancelled";
export interface OrganizationRecord {
  thread_id: string;
  agent_id: string;
  agent_name: string;
  title: string | null;
  status: string;
  latest_status?: string;
  last_success_at: number;
  last_attempt_at: number;
  error_code: string;
  diagnostic: Record<string, unknown>;
  job_id: string | null;
}
export interface OrganizationPage {
  items: OrganizationRecord[];
  total: number;
  offset: number;
  limit: number;
}
const scope = (agent: string, thread: string) =>
  `/agents/${encodeURIComponent(agent)}/threads/${encodeURIComponent(thread)}`;
export const metadataCommandId = () =>
  globalThis.crypto?.randomUUID?.() ??
  `metadata_${Date.now()}_${Math.random().toString(36).slice(2)}`;

export const conversationMetadataApi = {
  organizationPage: (
    age_filter: OrganizationAge,
    status_filter: OrganizationStatus,
    offset = 0,
    batch_id?: string,
  ) =>
    request<OrganizationPage>(
      `/settings/conversation-metadata/conversations?${new URLSearchParams({
        age_filter,
        status_filter,
        offset: String(offset),
        limit: "20",
        ...(batch_id ? { batch_id } : {}),
      })}`,
    ),
  cancelHistoryBatch: (batchId: string) =>
    request<HistoryBatch>(
      `/settings/conversation-metadata/batch/${encodeURIComponent(
        batchId,
      )}/cancel`,
      { method: "POST" },
    ),
  cancelJob: (agent: string, thread: string, jobId: string) =>
    request<MetadataJob>(
      `${scope(agent, thread)}/metadata-jobs/${encodeURIComponent(
        jobId,
      )}/cancel`,
      { method: "POST" },
    ),
  historyBatch: () =>
    request<HistoryBatch | null>("/settings/conversation-metadata/batch"),
  startHistoryBatch: (body: {
    command_id: string;
    agent_id?: string;
    thread_ids?: string[];
    age_filter?: OrganizationAge;
    status_filter?: OrganizationStatus;
  }) =>
    request<HistoryBatch>("/settings/conversation-metadata/batch", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  settings: () =>
    request<MetadataSettingsView>("/settings/conversation-metadata"),
  saveSettings: (body: MetadataSettings) =>
    request<MetadataSettingsView>("/settings/conversation-metadata", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  brief: (agent: string, thread: string) =>
    request<ConversationBrief>(`${scope(agent, thread)}/brief`),
  patch: (agent: string, thread: string, body: Record<string, unknown>) =>
    request<ConversationBrief>(`${scope(agent, thread)}/brief`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  generate: (agent: string, thread: string, kind: "title" | "brief") =>
    request<MetadataJob>(`${scope(agent, thread)}/metadata-jobs`, {
      method: "POST",
      body: JSON.stringify({ kind, command_id: metadataCommandId() }),
    }),
  batch: (agent: string, thread_ids: string[]) =>
    request<MetadataJob[]>(
      `/agents/${encodeURIComponent(agent)}/conversation-metadata-batch`,
      {
        method: "POST",
        body: JSON.stringify({
          kind: "brief",
          thread_ids,
          command_id: metadataCommandId(),
        }),
      },
    ),
  job: (agent: string, thread: string, jobId: string) =>
    request<MetadataJob>(
      `${scope(agent, thread)}/metadata-jobs/${encodeURIComponent(jobId)}`,
    ),
  titleAction: (
    agent: string,
    thread: string,
    body: {
      expected_revision: number;
      action: "apply" | "restore";
      title?: string;
    },
  ) =>
    request<ConversationBrief>(`${scope(agent, thread)}/title-action`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  events: (agent: string, thread: string, window: string, cursor?: string) =>
    request<ConversationEventPage>(
      `${scope(agent, thread)}/events?${new URLSearchParams({
        window,
        ...(cursor ? { cursor } : {}),
      })}`,
    ),
  digest: (agent: string, thread: string, window: string) =>
    request<ConversationDigest | MetadataJob>(
      `${scope(agent, thread)}/digests`,
      {
        method: "POST",
        body: JSON.stringify({ window }),
      },
    ),
  getDigest: (agent: string, thread: string, id: string) =>
    request<ConversationDigest>(
      `${scope(agent, thread)}/digests/${encodeURIComponent(id)}`,
    ),
  source: (agent: string, thread: string, ref: ConversationSourceRef) =>
    request<ConversationSource>(
      `${scope(agent, thread)}/metadata-source?${new URLSearchParams({
        kind: ref.kind,
        id: ref.id,
      })}`,
    ),
};
