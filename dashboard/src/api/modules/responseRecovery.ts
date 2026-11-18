import { request } from "../request";

export interface ResponseRecovery {
  response_id: string;
  retry_at: number;
  action: "retry" | "regenerate";
}

export function savedResponseRetry(
  diagnostic: unknown,
): { response_id: string; retry_at?: number } | null {
  if (
    !diagnostic ||
    typeof diagnostic !== "object" ||
    !("response_recovery" in diagnostic)
  )
    return null;
  const value = diagnostic.response_recovery;
  if (!value || typeof value !== "object") return null;
  const recovery = value as Partial<ResponseRecovery>;
  if (
    recovery.action !== "retry" ||
    typeof recovery.response_id !== "string" ||
    !recovery.response_id
  )
    return null;
  return {
    response_id: recovery.response_id,
    retry_at:
      typeof recovery.retry_at === "number" ? recovery.retry_at : undefined,
  };
}

export const responseRecoveryPath = (agent: string, thread: string) =>
  `/agents/${encodeURIComponent(agent)}/threads/${encodeURIComponent(
    thread,
  )}/response-recovery`;

export const responseRecoveryApi = {
  latest: (agent: string, thread: string) =>
    request<ResponseRecovery>(responseRecoveryPath(agent, thread)),
};
