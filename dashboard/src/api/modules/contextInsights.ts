import { request } from "../request";

export type ContextInsightsWindow = "last_24h" | "last_7d" | "last_30d" | "all";

export interface ContextInsightsKpi {
  active_sessions: number;
  total_sessions: number;
  total_tokens: number;
  turns: number;
  cache_hit_percent: number | null;
  model_calls?: number;
  cost: number | null;
  tool_calls: number | null;
  active_time_ms: number | null;
  balance: number | null;
}

export interface ContextInsightsSession {
  thread_id: string;
  agent_id: string;
  title: string;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  turns: number;
  model_calls: number;
  cache_hit_percent: number | null;
  last_active: number;
  cost: number | null;
  steps: number | null;
}

export interface ContextInsightsDayBucket {
  key: string;
  label: string;
  total_tokens: number;
  turns: number;
  cost: number | null;
}

export interface ContextInsightsDashboard {
  window: string;
  range_start?: number;
  range_end?: number;
  kpi: ContextInsightsKpi;
  by_day: ContextInsightsDayBucket[];
  sessions: ContextInsightsSession[];
  gaps: string[];
}

export const contextInsightsApi = {
  dashboard: (params: {
    window?: ContextInsightsWindow;
    q?: string;
    limit?: number;
  } = {}) => {
    const search = new URLSearchParams();
    if (params.window) search.set("window", params.window);
    if (params.q) search.set("q", params.q);
    if (params.limit != null) search.set("limit", String(params.limit));
    const qs = search.toString();
    return request<ContextInsightsDashboard>(
      `/context-insights/dashboard${qs ? `?${qs}` : ""}`,
    );
  },
};
