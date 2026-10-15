import { request } from "../request";

export interface ExternalSkill {
  source: string;
  slug: string;
  name: string;
  description: string;
  digest: string;
  manifest: string;
  files: string[];
  file_count: number;
  execution_context_id?: string;
  device_id?: string;
  needs_inspection?: boolean;
  path?: string;
}
export interface CapabilityCatalog {
  observed_at: number;
  os_user: string | null;
  dependencies: Record<string, string | null>;
  browser_dependency: boolean;
  entries: {
    id: string;
    kind: string;
    source: string;
    name: string;
    path?: string | null;
    status: string;
    version?: string | null;
    reason?: string;
    dependency_available?: boolean | null;
  }[];
}
const base = (agent: string) =>
  `/agents/${encodeURIComponent(agent)}/skills/external`;
export const externalSourcesApi = {
  discover: (agent: string, context?: string, signal?: AbortSignal) =>
    request<ExternalSkill[]>(
      `${base(agent)}/discover${
        context ? `?execution_context_id=${encodeURIComponent(context)}` : ""
      }`,
      { cache: "no-store", signal },
    ),
  inspect: (agent: string, candidate: ExternalSkill, signal?: AbortSignal) =>
    request<Partial<ExternalSkill>>(
      `${base(agent)}/inspect?${new URLSearchParams({
        execution_context_id: candidate.execution_context_id!,
        source: candidate.source,
        slug: candidate.slug,
        digest: candidate.digest,
      })}`,
      { cache: "no-store", signal },
    ),
  import: (agent: string, candidate: ExternalSkill) =>
    request(`${base(agent)}/import`, {
      method: "POST",
      body: JSON.stringify({
        execution_context_id: candidate.execution_context_id,
        source: candidate.source,
        slug: candidate.slug,
        digest: candidate.digest,
      }),
    }),
};
