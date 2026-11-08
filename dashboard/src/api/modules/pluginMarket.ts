import { request } from "../request";

export interface PluginInstallation {
  installed: boolean;
  enabled: boolean;
  show_in_chat: boolean;
}

export interface CatalogPlugin extends PluginInstallation {
  id: string;
  name: string;
  version: string;
  description: string;
  category: string;
  source_url: string;
}

export interface QuotaWindow {
  percent: number;
  resets_at: string | null;
}

export interface CostMeterState {
  installation: PluginInstallation;
  server_time: string;
  peak: {
    in_peak: boolean;
    reason: "weekday" | "weekend" | "holiday";
    next_change_at: string;
    calendar_supported: boolean;
    timezone: string;
  };
  go: {
    status: "unconfigured" | "idle" | "ok" | "error";
    error_code: string | null;
    fetched_at: string | null;
    attempted_at: string | null;
    rolling: QuotaWindow | null;
    weekly: QuotaWindow | null;
    monthly: QuotaWindow | null;
  };
  key_configured: boolean;
  subscription_expires_at: string | null;
  subscription_source: "manual" | null;
}

export const PLUGIN_MARKET_CHANGED = "octop:dashboard-plugins-changed";

export const pluginMarketApi = {
  catalog: () => request<CatalogPlugin[]>("/plugins/catalog"),
  install: (id: string, enabled = true, show_in_chat = true) =>
    request<PluginInstallation>(`/plugins/mine/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify({ enabled, show_in_chat }),
    }),
  uninstall: (id: string) =>
    request<void>(`/plugins/mine/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  state: () => request<CostMeterState>("/plugins/cost-meter/state"),
  refresh: () =>
    request<CostMeterState>("/plugins/cost-meter/refresh", { method: "POST" }),
  configure: (patch: {
    go_api_key?: string;
    clear_go_api_key?: boolean;
    subscription_expires_at?: string | null;
  }) =>
    request<CostMeterState>("/plugins/cost-meter/config", {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
};
