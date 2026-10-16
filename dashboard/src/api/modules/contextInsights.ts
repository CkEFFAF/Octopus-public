import { request } from "../request";

export type CoverageLevel = "complete" | "partial" | "unavailable";

export interface CoverageBlock {
  coverage: CoverageLevel;
  observed_start?: number | null;
  observed_head?: number | null;
  missing_ranges?: Array<Record<string, unknown>>;
  reason_codes?: string[];
  next_cursor?: string | number | null;
  source?: string | null;
  quality?: string | null;
}

export interface InsightsStats {
  model_requests?: number | null;
  human_turns?: number | null;
  trajectory_events?: number | null;
  turns?: number;
  steps?: number;
  legacy_alias?: Record<string, string>;
  input_tokens?: number | null;
  output_tokens?: number | null;
  cache_hit_ratio?: number | null;
  llm_duration_ms?: number | null;
  used_tokens?: number;
  max_tokens?: number;
  tool_schema_count?: number | null;
  logical_call_count?: number | null;
  attempt_count?: number | null;
}

export interface InsightsInspect {
  schema_version: string;
  as_of: string;
  revision?: string | null;
  meter_source?: string;
  breakdown?: {
    max_tokens: number;
    used_tokens: number;
    capacity_source?: string;
    capacity_tokens?: number | null;
    compatibility_capacity_tokens?: number;
    segments: Array<{ key: string; tokens: number }>;
  };
  stats?: InsightsStats;
  meters?: Record<string, unknown>;
  coverage?: CoverageBlock;
  trend?: Array<Record<string, unknown>>;
  execution?: Record<string, unknown> | null;
}

export interface InsightsRequest {
  schema_version: string;
  request: Record<string, unknown>;
  effective_binding?: Record<string, unknown>;
  turn_steps?: Array<Record<string, unknown>>;
  components?: Array<Record<string, unknown>>;
  coverage?: CoverageBlock;
  next_cursor?: number | null;
}

function base(agentId: string, threadId: string): string {
  return `/agents/${encodeURIComponent(agentId)}/threads/${encodeURIComponent(
    threadId,
  )}/context-insights`;
}

export const contextInsightsApi = {
  inspect: (
    agentId: string,
    threadId: string,
    params: { include?: string[]; trendLimit?: number } = {},
  ) => {
    const search = new URLSearchParams();
    if (params.include?.length) search.set("include", params.include.join(","));
    if (params.trendLimit != null)
      search.set("trend_limit", String(params.trendLimit));
    const qs = search.toString();
    return request<InsightsInspect>(`${base(agentId, threadId)}${qs ? `?${qs}` : ""}`);
  },

  request: (
    agentId: string,
    threadId: string,
    requestId: string,
    params: {
      includeContent?: boolean;
      cursor?: number;
      limit?: number;
    } = {},
  ) => {
    const search = new URLSearchParams();
    if (params.includeContent) search.set("include_content", "true");
    if (params.cursor != null) search.set("cursor", String(params.cursor));
    if (params.limit != null) search.set("limit", String(params.limit));
    const qs = search.toString();
    return request<InsightsRequest>(
      `${base(agentId, threadId)}/requests/${encodeURIComponent(requestId)}${
        qs ? `?${qs}` : ""
      }`,
    );
  },

  traceRead: (
    agentId: string,
    threadId: string,
    eventId: string,
    params: { part?: string; cursor?: number; limit?: number } = {},
  ) => {
    const search = new URLSearchParams();
    if (params.part) search.set("part", params.part);
    if (params.cursor != null) search.set("cursor", String(params.cursor));
    if (params.limit != null) search.set("limit", String(params.limit));
    const qs = search.toString();
    return request<Record<string, unknown>>(
      `${base(agentId, threadId)}/trace/${encodeURIComponent(eventId)}${
        qs ? `?${qs}` : ""
      }`,
    );
  },
};
