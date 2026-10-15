import { request } from "../request";
import type { Device } from "./devices";

export type ExecutionTarget = Omit<
  Device,
  "device_id" | "roots" | "last_seen_at"
> & {
  device_id: string | null;
  target_kind: "device" | "local";
};
export interface TargetSelection {
  device_id: string | null;
  working_dir: string | null;
  target_kind?: "device" | "local";
}

export type WorkMode =
  | "agentic"
  | "plan"
  | "ask"
  | "debug"
  | "multitask"
  | "cowork"
  | "computer_use"
  | "deep_research"
  | "team";
export interface RequestComponent {
  kind: string;
  index: number;
  source_id?: string | null;
  source_type?: string;
  source_path?: string | null;
  tool_call_id?: string | null;
  estimated_tokens: number;
  content: string;
  content_truncated: boolean;
  sha256: string;
}
export interface RequestSnapshot {
  request_id: string;
  seq: number;
  status: string;
  created_at: number;
  thread_id: string;
  agent_id: string;
  model: string | null;
  context_id: string | null;
  estimated_input_tokens: number;
  estimated_tokens_by_kind?: Record<string, number>;
  component_count?: number | null;
  component_counts?: Record<string, number>;
  components_truncated?: boolean;
  omitted_component_count?: number;
  metadata_truncated?: boolean;
  actual_usage: Record<string, number> | null;
  duration_ms: number | null;
  ttft_ms: number | null;
  transformation?: {
    kind: "summarization" | "message_rewrite";
    scope: "messages";
    before_estimated_tokens: number;
    after_estimated_tokens: number;
    before_message_count: number;
    after_message_count: number;
    summary_sha256: string | null;
    removed_source_ids: string[];
    source_ids_truncated: boolean;
  } | null;
  composition: Record<string, number>;
  components: RequestComponent[];
}
export interface RequestHistory {
  requests: RequestSnapshot[];
  has_more: boolean;
  next_before: number | null;
}
export interface RunEvent {
  event_id: string;
  seq: number;
  run_id: string;
  context_id: string | null;
  kind: string;
  status: string;
  created_at: number;
  updated_at: number;
  payload: Record<string, unknown>;
}
export interface RunHistory {
  events: RunEvent[];
  has_more: boolean;
  next_before: number | null;
}
export interface ExecutionContext {
  context_id: string;
  device_id: string | null;
  target_kind?: "device" | "local";
  working_dir: string | null;
  work_mode: WorkMode;
  policy_revision: number;
  grant_version: number;
}
const base = (agent: string, thread: string) =>
  `/agents/${encodeURIComponent(agent)}/threads/${encodeURIComponent(
    thread,
  )}/requests`;
export const executionApi = {
  localAvailable: () => request<{ available: boolean }>("/execution-local"),
  target: (context: string) =>
    request<ExecutionTarget>(
      `/execution-contexts/${encodeURIComponent(context)}/target`,
    ),
  defaultTarget: () => request<TargetSelection>("/execution-default"),
  saveDefaultTarget: (
    device_id: string | null,
    working_dir?: string,
    target_kind: "device" | "local" = "device",
  ) =>
    request<TargetSelection>("/execution-default", {
      method: "PUT",
      body: JSON.stringify({
        device_id,
        working_dir: working_dir ?? null,
        target_kind,
      }),
    }),
  decide: (
    agent: string,
    thread: string,
    event: string,
    version: number,
    choice: number,
  ) =>
    request<RunEvent>(
      `/agents/${encodeURIComponent(agent)}/threads/${encodeURIComponent(
        thread,
      )}/workflows/${encodeURIComponent(event)}/decision`,
      { method: "POST", body: JSON.stringify({ version, choice }) },
    ),
  runs: (agent: string, thread: string, before?: number, run?: string) =>
    request<RunHistory>(
      `/agents/${encodeURIComponent(agent)}/threads/${encodeURIComponent(
        thread,
      )}/run-events?${new URLSearchParams({
        limit: "100",
        ...(before ? { before: String(before) } : {}),
        ...(run ? { run_id: run } : {}),
      })}`,
    ),
  createContext: (values: {
    device_id?: string;
    target_kind?: "device" | "local";
    working_dir?: string;
    agent_id?: string;
    thread_id?: string;
    work_mode?: WorkMode;
  }) =>
    request<ExecutionContext>("/execution-contexts", {
      method: "POST",
      body: JSON.stringify(values),
    }),
  call: <T>(
    context: string,
    action: string,
    params: Record<string, unknown>,
    signal?: AbortSignal,
  ) =>
    request<{ context: ExecutionContext; result: T }>(
      `/execution-contexts/${encodeURIComponent(context)}/call`,
      { method: "POST", body: JSON.stringify({ action, params }), signal },
    ).then((value) => value.result),
  requests: (agent: string, thread: string, before?: number) =>
    request<RequestHistory>(
      `${base(agent, thread)}?limit=100${before ? `&before=${before}` : ""}`,
    ),
  request: (agent: string, thread: string, id: string) =>
    request<RequestSnapshot>(
      `${base(agent, thread)}/${encodeURIComponent(id)}`,
    ),
};
