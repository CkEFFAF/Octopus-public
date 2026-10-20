import { request } from "../request";
import { fileScope } from "./fileSources";
export interface ActivityNode {
  id: string;
  type: string;
  name: string;
  status: string;
  observed_status?: string;
  outcome?: string;
  declared_status?: string;
  reason?: string;
  run_id?: string;
  context_id?: string;
  task_id?: string;
  attempt_id?: string;
  created_at?: number;
  updated_at: number;
  details?: Record<string, unknown>;
  dependencies_known: boolean;
}
export interface ActivitySnapshot {
  nodes: ActivityNode[];
  edges: { from: string; to: string; kind: string }[];
  observed_at: number;
  scope_truncated: boolean;
  active_scope_truncated?: boolean;
  next_before: number | null;
  counts: {
    subagents: number;
    jobs: number;
    parallel: number | null;
    completed: number;
  };
}
export const activityApi = {
  snapshot: (a: string, t: string, before?: number) =>
    request<ActivitySnapshot>(
      `${fileScope(a, t)}/activity${before ? `?before=${before}` : ""}`,
    ),
};
