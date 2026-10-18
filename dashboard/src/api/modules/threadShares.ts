import { request } from "../request";

export interface SharedMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
}

export interface SharePreview {
  preview_digest: string;
  title: string;
  timezone: string;
  messages: SharedMessage[];
  message_count: number;
}

export interface ThreadShare {
  share_id: string;
  public_url?: string | null;
  public_path?: string | null;
  title: string;
  agent_id: string;
  thread_id: string;
  created_at: number;
  expires_at: number | null;
  revoked_at: number | null;
  status: "active" | "expired" | "revoked";
  message_count: number;
}

export interface ThreadSharesPage {
  shares: ThreadShare[];
  next_before: string | null;
  has_more: boolean;
}

function threadBase(agentId: string, threadId: string) {
  return `/agents/${encodeURIComponent(agentId)}/threads/${encodeURIComponent(
    threadId,
  )}`;
}

export const threadSharesApi = {
  preview: (agentId: string, threadId: string) =>
    request<SharePreview>(`${threadBase(agentId, threadId)}/share-preview`),
  create: (
    agentId: string,
    threadId: string,
    previewDigest: string,
    expiry: number | null,
  ) =>
    request<ThreadShare>(`${threadBase(agentId, threadId)}/shares`, {
      method: "POST",
      body: JSON.stringify({
        preview_digest: previewDigest,
        expires_in_seconds: expiry,
      }),
    }),
  list: (
    scope?: { agentId: string; threadId: string },
    before?: string | null,
  ) =>
    request<ThreadSharesPage>(
      `${
        scope
          ? `${threadBase(scope.agentId, scope.threadId)}/shares`
          : "/thread-shares"
      }?limit=50${
        before == null ? "" : `&before=${encodeURIComponent(before)}`
      }`,
    ),
  revoke: (shareId: string) =>
    request<void>(`/thread-shares/${encodeURIComponent(shareId)}`, {
      method: "DELETE",
    }),
};
