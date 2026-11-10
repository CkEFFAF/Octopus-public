import { request } from "../request";

export type NodeKind =
  | "entry"
  | "agent"
  | "script"
  | "condition"
  | "event"
  | "wait_event"
  | "wait_time"
  | "fork"
  | "join"
  | "end";
export type Binding = { path: string } | { value: unknown };
export interface ContextPolicy {
  before: {
    session?: "current" | "new";
    history?: "inherit" | "recent" | "empty";
    recent_turns?: number;
    inject?: string | null;
    inject_from?: Binding | null;
  };
  after: { session?: "keep" | "restore"; context?: "keep" | "restore" };
}
export interface GraphNode {
  id: string;
  kind: NodeKind;
  label: string;
  position: { x: number; y: number };
  inputs?: Record<string, Binding>;
  assign?: Record<string, Binding>;
  context?: ContextPolicy;
  [key: string]: unknown;
}
export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  port: "next" | "true" | "false" | "error";
  label?: string;
}
export interface GraphDefinition {
  schema_version?: 1;
  name: string;
  description?: string;
  agent_id: string;
  origin_thread_id?: string;
  execution_context_id?: string;
  initial_variables?: Record<string, unknown>;
  nodes: GraphNode[];
  edges: GraphEdge[];
  limits?: { max_steps: number; max_seconds: number; max_parallel: number };
  schedule?: {
    cron: string;
    timezone: string;
    overlap: "skip" | "parallel";
    enabled: boolean;
  } | null;
  event_start?: boolean;
}
export interface Issue {
  message: string;
  node_id?: string;
  edge_id?: string;
}
export interface GraphView {
  graph_id: string;
  revision: number;
  published_revision: number | null;
  definition: GraphDefinition;
  issues: Issue[];
  archived: boolean;
}
export interface GraphSummary {
  graph_id: string;
  name: string;
  revision: number;
  published_revision: number | null;
  updated_at: number;
}
export interface GraphRun {
  id: string;
  graph_id: string;
  version: number;
  status: string;
  steps: number;
  max_steps: number;
  deadline: number;
  error: string;
  created_at: number;
  node_states?: Activation[];
}
export interface Activation {
  id: string;
  node_id: string;
  kind: NodeKind;
  ordinal: number;
  status: string;
  error: string;
  created_at: number;
  input?: unknown;
  output?: unknown;
  before?: { agent_id: string; thread_id: string; recipe?: unknown };
  after?: unknown;
  evidence?: unknown;
}
export interface Page<T> {
  items: T[];
  total: number;
}
const base = "/workflow-graphs";
const post = <T>(path: string, body: unknown = {}) =>
  request<T>(base + path, { method: "POST", body: JSON.stringify(body) });
const id = encodeURIComponent;
export const workflowGraphsApi = {
  normalize: (definition: GraphDefinition) =>
    post<{ definition: GraphDefinition; issues: Issue[] }>(
      "/normalize",
      definition,
    ),
  version: (graph: string, version: number) =>
    request<GraphDefinition>(`${base}/${id(graph)}/versions/${version}`),
  cancelJobs: (run: string) =>
    post<{ run: GraphRun; jobs: unknown[] }>(`/runs/${id(run)}/cancel-jobs`),
  list: (offset = 0) =>
    request<Page<GraphSummary>>(`${base}?offset=${offset}&limit=50`),
  get: (graph: string) => request<GraphView>(`${base}/${id(graph)}`),
  save: (graph_id: string, revision: number, definition: GraphDefinition) =>
    request<GraphView>(base, {
      method: "PUT",
      body: JSON.stringify({ graph_id, revision, definition }),
    }),
  validate: (definition: GraphDefinition) =>
    post<Issue[]>("/validate", definition),
  publish: (graph: string, revision: number) =>
    post<GraphView>(`/${id(graph)}/publish`, { revision }),
  archive: (graph: string, revision: number) =>
    post(`/${id(graph)}/archive`, { revision }),
  start: (
    graph: string,
    variables: Record<string, unknown> = {},
    request_id: string = crypto.randomUUID(),
  ) => post<GraphRun>(`/${id(graph)}/start`, { request_id, variables }),
  runs: (graph: string) => request<Page<GraphRun>>(`${base}/${id(graph)}/runs`),
  run: (run: string) => request<GraphRun>(`${base}/runs/${id(run)}`),
  timeline: (run: string, offset = 0) =>
    request<Page<Activation>>(
      `${base}/runs/${id(run)}/timeline?offset=${offset}`,
    ),
  inspect: (activation: string) =>
    request<Activation>(`${base}/activations/${id(activation)}`),
  control: (
    run: string,
    action: string,
    budget: { max_steps?: number; extra_seconds?: number } = {},
  ) => post<GraphRun>(`/runs/${id(run)}/control`, { action, ...budget }),
  retry: (activation: string) =>
    post<GraphRun>(`/activations/${id(activation)}/retry`),
  reconcile: (activation: string) =>
    post<Activation>(`/activations/${id(activation)}/reconcile`),
  capability: (graph: string, revoke = false) =>
    post<{ token: string; callback_url: string }>(
      `/${id(graph)}/capability?revoke=${revoke}`,
    ),
};
