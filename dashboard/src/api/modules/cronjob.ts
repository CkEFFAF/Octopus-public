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

export const octopCronApi = {
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
