import { request } from "../request";

export const MODEL_TASKS = [
  "chat",
  "coding",
  "reasoning",
  "research",
  "vision",
  "long_context",
  "title",
  "summary",
  "memory",
] as const;
export type ModelTask = (typeof MODEL_TASKS)[number];
export interface ModelRoutingConfig {
  enabled: boolean;
  tasks: Partial<Record<ModelTask, string | null>>;
}
export interface ModelRouteDecision {
  task: ModelTask;
  model: string | null;
  source: "manual" | "task" | "automatic" | "default";
  reason: string;
  available: boolean;
}
export interface ModelRoutingView extends ModelRoutingConfig {
  models: Array<{
    value: string;
    name: string;
    model: string;
    provider_name: string;
    input: string[];
  }>;
  resolved: Record<ModelTask, ModelRouteDecision>;
  auxiliary_overrides: Partial<Record<ModelTask, string>>;
  memory_apply: "next_expert_reload";
}
export interface ModelRoutePreview {
  text: string;
  task?: ModelTask;
  has_images?: boolean;
  context_tokens?: number;
}
export const modelRoutingApi = {
  get: () => request<ModelRoutingView>("/settings/model-routing"),
  save: (config: ModelRoutingConfig) =>
    request<ModelRoutingView>("/settings/model-routing", {
      method: "PUT",
      body: JSON.stringify(config),
    }),
  preview: (input: ModelRoutePreview) =>
    request<ModelRouteDecision>("/settings/model-routing/preview", {
      method: "POST",
      body: JSON.stringify(input),
    }),
};
