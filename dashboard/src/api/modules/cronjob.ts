import { request } from "../request";
import type {
  OctopCronRow,
  OctopCronCreateBody,
  OctopCronPatchBody,
} from "../types";

export interface OctopCronSettings {
  timezone: string;
}

export interface CronTaskExamples {
  zh?: string[];
  en?: string[];
}

export interface ScheduleQuery {
  agent_id?: string;
  thread_id?: string;
  reminder?: boolean;
  category?: "once" | "repeat" | "ended";
  lifecycle?: "active" | "completed" | "failed" | "inactive";
  search?: string;
}
export interface SchedulePage {
  items: OctopCronRow[];
  next_schedule?: Pick<OctopCronRow, "next_run_at" | "timezone"> | null;
  total: number;
  has_more: boolean;
  next_offset: number | null;
  counts: { schedules: number; reminders: number };
  lifecycle_counts?: Record<string, number>;
}

export const octopCronApi = {
  page: (query: ScheduleQuery, offset = 0, limit = 5) => {
    const params = new URLSearchParams({
      offset: String(offset),
      limit: String(limit),
    });
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined && value !== "") params.set(key, String(value));
    });
    return request<SchedulePage>(`/cron?${params}`);
  },
  settings: () => request<OctopCronSettings>("/cron/settings"),

  list: (agentId: string, includeSelfReminders = false, threadId?: string) =>
    request<OctopCronRow[]>(
      `/agents/${agentId}/cron?include_self_reminders=${includeSelfReminders}${
        threadId ? `&thread_id=${encodeURIComponent(threadId)}` : ""
      }`,
    ),
  attempts: (agentId: string, cronId: string, before?: number | null) =>
    request<CronAttemptPage>(
      `/agents/${agentId}/cron/${cronId}/attempts${
        before ? `?before=${before}` : ""
      }`,
    ),

  create: (agentId: string, body: OctopCronCreateBody) =>
    request<OctopCronRow>(`/agents/${agentId}/cron`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  get: (agentId: string, cronId: string) =>
    request<OctopCronRow>(`/agents/${agentId}/cron/${cronId}`),

  patch: (agentId: string, cronId: string, body: OctopCronPatchBody) =>
    request<OctopCronRow>(`/agents/${agentId}/cron/${cronId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  delete: (agentId: string, cronId: string) =>
    request<void>(`/agents/${agentId}/cron/${cronId}`, { method: "DELETE" }),

  runNow: (agentId: string, cronId: string) =>
    request<void>(`/agents/${agentId}/cron/${cronId}/run-now`, {
      method: "POST",
    }),
};

export interface CronAttempt {
  id: number;
  attempt_id: string;
  source_thread_id: string | null;
  actual_thread_id: string | null;
  run_id: string | null;
  reason: string;
  status: string;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
  public_error: string | null;
  result_excerpt: string | null;
}
export interface CronAttemptPage {
  items: CronAttempt[];
  has_more: boolean;
  next_cursor: number | null;
}
