import { request } from "../request";

export interface ResponseRecovery {
  response_id: string;
  retry_at: number;
  action: "retry" | "regenerate";
}

export const responseRecoveryPath = (agent: string, thread: string) =>
  `/agents/${encodeURIComponent(agent)}/threads/${encodeURIComponent(
    thread,
  )}/response-recovery`;

export const responseRecoveryApi = {
  latest: (agent: string, thread: string) =>
    request<ResponseRecovery>(responseRecoveryPath(agent, thread)),
};
