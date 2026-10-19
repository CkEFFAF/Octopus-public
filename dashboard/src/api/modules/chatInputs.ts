import { request } from "../request";

export type ChatInputReceipt<Snapshot = Record<string, unknown>> = {
  event_id: string;
  seq: number;
  status: string;
  kind: string;
  run_id: string;
  created_at: number;
  payload: { command_id: string; snapshot?: Snapshot; text?: string };
};
export type ChatInputSnapshot<Snapshot = Record<string, unknown>> = {
  inputs: ChatInputReceipt<Snapshot>[];
  runtime: { run_id: string; phase: string } | null;
  capabilities: { queue: boolean; steer: boolean };
};
const path = (agent: string, thread: string) =>
  `/agents/${encodeURIComponent(agent)}/threads/${encodeURIComponent(
    thread,
  )}/inputs`;
export const chatInputsApi = {
  list: <Snapshot extends object = Record<string, unknown>>(
    agent: string,
    thread: string,
  ) => request<ChatInputSnapshot<Snapshot>>(path(agent, thread)),
  queue: <Snapshot extends object>(
    agent: string,
    thread: string,
    commandId: string,
    snapshot: Snapshot,
    turn: Record<string, unknown>,
  ) =>
    request<ChatInputReceipt>(path(agent, thread), {
      method: "POST",
      body: JSON.stringify({ command_id: commandId, snapshot, turn }),
    }),
  withdraw: (agent: string, thread: string, id: string) =>
    request<ChatInputReceipt>(
      `${path(agent, thread)}/${encodeURIComponent(id)}`,
      { method: "DELETE" },
    ),
  steer: (
    agent: string,
    thread: string,
    id: string,
    runId: string,
    text: string,
  ) =>
    request<ChatInputReceipt & { phase?: string }>(
      `${path(agent, thread)}/steer`,
      {
        method: "POST",
        body: JSON.stringify({
          command_id: id,
          thread_id: thread,
          run_id: runId,
          text,
        }),
      },
    ),
};
