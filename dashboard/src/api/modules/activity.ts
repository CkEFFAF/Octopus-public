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
export interface BackgroundJobPage {
  items: Array<{
    id: string;
    thread_id: string;
    title: string | null;
    status: string;
    updated_at: number;
    lifecycle: string;
  }>;
  counts: Record<string, number>;
  total: number;
  offset: number;
  limit: number;
}
export const activityApi = {
  backgroundJobs: (
    agent: string,
    lifecycle: string,
    thread?: string,
    offset = 0,
  ) => {
    const query = new URLSearchParams({
      lifecycle,
      offset: String(offset),
      limit: "20",
    });
    if (thread) query.set("thread_id", thread);
    return request<BackgroundJobPage>(
      `/agents/${encodeURIComponent(agent)}/background-jobs?${query}`,
    );
  },
  snapshot: (a: string, t: string, before?: number) =>
    request<ActivitySnapshot>(
      `${fileScope(a, t)}/activity${before ? `?before=${before}` : ""}`,
    ),
};
