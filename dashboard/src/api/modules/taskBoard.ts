import { request } from "../request";

export type TaskStatus = "planning" | "todo" | "running" | "done" | "failed";
export interface TaskReview {
  reviewer: string;
  scores: number[];
  evidence: string;
  passed: boolean;
  created_at: string;
  run_id: string;
  model: string;
  baseline_scores: number[];
  rounds: {
    criterion: number;
    round: number;
    score: number;
    baseline: number;
    evidence: string;
  }[];
  evidence_chars: number;
  truncated_chars: number;
  usage: Record<string, unknown>;
}
export interface TaskRun {
  id: string;
  request_id: string;
  contract: string;
  agent_id: string;
  state: "running" | "succeeded" | "failed" | "interrupted";
  started_at: string;
  ended_at: string | null;
  thread_id: string | null;
  output: string;
  error: string;
  review: TaskReview | null;
  phase: "executing" | "reviewing" | "finished";
  acceptance_error: string;
  attempts: TaskReview[];
}
export interface TaskSchedule {
  cron: string;
  timezone: string;
  enabled: boolean;
  next_run?: string | null;
  last_trigger?: string | null;
}
export interface BoardTask {
  id: string;
  title: string;
  description: string;
  prompt: string;
  project_id: string;
  agent_id: string;
  tags: string[];
  device_id: string;
  status: TaskStatus;
  parent_id: string;
  archived: boolean;
  pin: string;
  goal: string;
  progress: string;
  next_step: string;
  handovers: {
    goal: string;
    progress: string;
    next_step: string;
    from_agent: string;
    to_agent: string;
    created_at: string;
  }[];
  runs: TaskRun[];
  review: TaskReview | null;
  schedule: TaskSchedule | null;
  created_at: string;
  updated_at: string;
  model: string;
  reviewer_model: string;
  acceptance: "manual" | "automatic";
  auto_repair: boolean;
  continue_session: boolean;
}
export interface BoardSnapshot {
  revision: number;
  timezone: string;
  tasks: BoardTask[];
  tag_prefixes: Record<string, string>;
}
export interface TaskDraft {
  title: string;
  description: string;
  prompt: string;
  tags: string[];
  project_id: string;
  agent_id: string;
  parent_id: string;
}
export type BoardOperation =
  | "create"
  | "update"
  | "move"
  | "archive"
  | "restore"
  | "confirm"
  | "handover"
  | "parent"
  | "schedule"
  | "run"
  | "cancel"
  | "review"
  | "tags"
  | "verify";
export const taskBoardApi = {
  get: () => request<BoardSnapshot>("/task-board"),
  act: (
    revision: number,
    action: BoardOperation,
    task_id: string,
    payload: Record<string, unknown> = {},
  ) =>
    request<BoardSnapshot>("/task-board/actions", {
      method: "POST",
      body: JSON.stringify({ revision, action, task_id, payload }),
    }),
  parse: (agent_id: string, text: string, model = "") =>
    request<TaskDraft>("/task-board/parse", {
      method: "POST",
      body: JSON.stringify({ agent_id, text, model }),
    }),
};
