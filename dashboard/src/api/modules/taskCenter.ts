import { request } from "../request";

export interface TaskOverviewItem {
  id: string;
  source_id: string;
  source: "work_item" | "board" | "job" | "subagent" | "plan";
  title: string;
  status: string;
  lifecycle: string;
  agent_id: string;
  agent_name: string;
  thread_id: string | null;
  thread_title: string | null;
  updated_at: number;
  summary: string;
  stale: boolean;
  declared: boolean;
}
export interface TaskOverviewPage {
  items: TaskOverviewItem[];
  total: number;
  counts: Record<string, number>;
  offset: number;
  limit: number;
  has_more: boolean;
  agents: { value: string; label: string }[];
  threads: { value: string; label: string; agent_id: string }[];
  observed_at: number;
}
export interface TaskOverviewQuery {
  agent_id?: string;
  thread_id?: string;
  lifecycle?: string;
  query?: string;
  offset?: number;
  include_board?: boolean;
  limit?: number;
}
export const taskCenterApi = {
  page: (filters: TaskOverviewQuery) => {
    const params = new URLSearchParams({ limit: "20" });
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined && value !== "") params.set(key, String(value));
    });
    return request<TaskOverviewPage>(`/task-center?${params}`);
  },
};
