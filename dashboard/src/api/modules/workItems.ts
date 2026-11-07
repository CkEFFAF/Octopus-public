import { request } from "../request";

export type WorkItemStatus =
  | "queued"
  | "running"
  | "waiting_input"
  | "waiting_review"
  | "blocked"
  | "failed"
  | "completed"
  | "cancelled"
  | "unknown";
export interface WorkItemSummary {
  task_id: string;
  title: string;
  status: WorkItemStatus;
  origin_thread_id: string | null;
  updated_at: number;
  cancel_requested: boolean | number;
}
export interface WorkItemDetail extends WorkItemSummary {
  agent_id: string;
  instructions: string;
  origin_thread_missing: boolean;
  current_run_id: string | null;
  current_attempt_id: string | null;
  progress: {
    phase: string | null;
    active_tools: string[];
    last_event_at: number | null;
    block_reason: string | null;
    needs_approval: boolean;
    needs_credential: boolean;
    permission_denied: boolean;
  };
}
export interface WorkItemCreate {
  agent_id: string;
  origin_thread_id: string;
  title: string;
  instructions: string;
  execution: {
    target_kind: "device" | "local";
    device_id: string | null;
    working_dir: string | null;
  };
}
const taskPath = (id: string) => `/work-items/${encodeURIComponent(id)}`;
export const workItemsApi = {
  list: (originThreadId?: string) =>
    request<{ items: WorkItemSummary[]; has_more: boolean }>(
      `/work-items?status_group=all&limit=50${
        originThreadId
          ? `&origin_thread_id=${encodeURIComponent(originThreadId)}`
          : ""
      }`,
    ),
  detail: (id: string) => request<WorkItemDetail>(taskPath(id)),
  create: (body: WorkItemCreate, commandId: string) =>
    request<{ task_id: string }>("/work-items", {
      method: "POST",
      body: JSON.stringify({
        ...body,
        command_id: commandId,
        schema_version: 1,
      }),
    }),
  input: (task: WorkItemDetail, text: string, commandId: string) =>
    request(`${taskPath(task.task_id)}/inputs`, {
      method: "POST",
      body: JSON.stringify({
        text,
        command_id: commandId,
        target_run_id: task.current_run_id,
        target_attempt_id: task.current_attempt_id,
        schema_version: 1,
      }),
    }),
  cancel: (id: string, commandId: string) =>
    request<{
      cancel_requested: boolean;
      status: WorkItemStatus;
      terminated: boolean;
    }>(`${taskPath(id)}/cancel`, {
      method: "POST",
      body: JSON.stringify({
        command_id: commandId,
        scope: "task",
        schema_version: 1,
      }),
    }),
};
