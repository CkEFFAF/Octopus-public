import { request, getAuthToken } from "../request";
import { getApiUrl } from "../config";
import type { CollaborationResource } from "./collaboration";

export function fileScope(agent: string, thread: string) {
  return `/agents/${encodeURIComponent(agent)}/threads/${encodeURIComponent(
    thread,
  )}`;
}
export const fileSourcesApi = {
  open: (
    agent: string,
    thread: string,
    source: {
      kind: "execution" | "workspace" | "resource";
      context_id?: string;
      path?: string;
      resource_id?: string;
    },
  ) =>
    request<{
      resource: CollaborationResource;
      source: { kind: string; version: string };
    }>(`${fileScope(agent, thread)}/file-sources/open`, {
      method: "POST",
      body: JSON.stringify(source),
    }),
  mediaUrl: (agent: string, thread: string, resource: string) =>
    `${getApiUrl(
      `${fileScope(agent, thread)}/resources/${encodeURIComponent(
        resource,
      )}/content`,
    )}?${new URLSearchParams({ access_token: getAuthToken() })}`,
};
