import { afterEach, expect, it, vi } from "vitest";
import {
  appendUserMessage,
  getSnapshot,
  ingestHarnessChunk,
  recoverResponse,
  removeSession,
} from "./chatStore";

const session = "recovery-thread";

it("discards failed tool arguments while retaining completed work and another speaker", () => {
  appendUserMessage(session, {
    id: "question",
    role: "user",
    content: "q",
    timestamp: 1,
  });
  ingestHarnessChunk(
    session,
    { type: "token", node: "model", content: "Committed progress" },
    "host",
  );
  ingestHarnessChunk(session, {
    type: "tool_call_chunk",
    id: "done-tool",
    index: 0,
    name: "write_file",
    args: "{}",
  });
  ingestHarnessChunk(session, {
    type: "tool_result",
    node: "tools",
    messages: [
      { type: "tool", tool_call_id: "done-tool", content: "Already written" },
    ],
  });
  ingestHarnessChunk(session, {
    type: "token",
    node: "model",
    content: "Failed partial",
  });
  ingestHarnessChunk(session, {
    type: "tool_call_chunk",
    id: "failed-tool",
    index: 0,
    name: "write_file",
    args: '{"path":',
  });
  ingestHarnessChunk(session, {
    type: "token",
    node: "model",
    agent_id: "peer",
    content: "Peer keeps working",
  });
  ingestHarnessChunk(session, {
    type: "custom",
    data: {
      octop_model_retry: { phase: "retrying", attempt: 2, max_attempts: 3 },
    },
  });
  const messages = getSnapshot(session).messages;
  expect(
    messages.some((message) => message.content.includes("Failed partial")),
  ).toBe(false);
  expect(
    messages.some((message) => message.toolData?.callId === "failed-tool"),
  ).toBe(false);
  expect(
    messages.find((message) => message.toolData?.callId === "done-tool")
      ?.toolData?.output,
  ).toBe("Already written");
  expect(
    messages.some((message) => message.content.includes("Committed progress")),
  ).toBe(true);
  expect(
    messages.some((message) => message.content === "Peer keeps working"),
  ).toBe(true);
  ingestHarnessChunk(session, {
    type: "tool_call_chunk",
    id: "new-tool",
    index: 0,
    name: "read_file",
    args: "{}",
  });
  ingestHarnessChunk(session, {
    type: "tool_result",
    node: "tools",
    messages: [
      { type: "tool", tool_call_id: "new-tool", content: "New output" },
    ],
  });
  expect(
    getSnapshot(session)
      .messages.filter((message) => message.toolData)
      .map((message) => message.toolData?.callId),
  ).toEqual(["done-tool", "new-tool"]);
});
vi.mock("../../../api/config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
}));
afterEach(() => {
  removeSession(session);
  vi.unstubAllGlobals();
});

it("posts a recovery identity without sending another user message or attachment payload", async () => {
  appendUserMessage(session, {
    id: "original",
    role: "user",
    content: "original question",
    timestamp: 1,
    attachments: [{ url: "/file", filename: "source.pdf", kind: "file" }],
  });
  const frames = [
    { type: "recovery_ack", status: "accepted", response_id: "response" },
    { type: "run_phase", run_id: "retry-run", phase: "model" },
    { type: "token", node: "model", content: "Recovered" },
    { type: "run_phase", run_id: "retry-run", phase: "completed" },
    { type: "done" },
  ];
  const fetcher = vi.fn(
    async () =>
      new Response(
        frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join(""),
        { status: 200 },
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  expect(await recoverResponse(session, "agent", "response", "command")).toBe(
    "completed",
  );
  const [url, options] = fetcher.mock.calls[0] as unknown as [
    string,
    RequestInit,
  ];
  expect(url).toContain("/response-recovery");
  expect(JSON.parse(options.body as string)).toEqual({
    response_id: "response",
    command_id: "command",
  });
  expect(
    getSnapshot(session).messages.filter((message) => message.role === "user"),
  ).toHaveLength(1);
  expect(getSnapshot(session).messages[0].attachments?.[0].filename).toBe(
    "source.pdf",
  );
  expect(getSnapshot(session).isStreaming).toBe(false);
});

it("replaces an uncommitted model attempt while retaining the original question", () => {
  appendUserMessage(session, {
    id: "user",
    role: "user",
    content: "q",
    timestamp: 1,
  });
  ingestHarnessChunk(session, {
    type: "token",
    node: "model",
    content: "Partial",
  });
  ingestHarnessChunk(session, {
    type: "custom",
    data: {
      octop_model_retry: {
        phase: "waiting_retry",
        attempt: 1,
        max_attempts: 3,
        retry_at: 200,
      },
    },
  });
  expect(getSnapshot(session).modelRetry?.phase).toBe("waiting_retry");
  ingestHarnessChunk(session, {
    type: "custom",
    data: {
      octop_model_retry: { phase: "retrying", attempt: 2, max_attempts: 3 },
    },
  });
  ingestHarnessChunk(session, {
    type: "token",
    node: "model",
    content: "Full answer",
  });
  expect(
    getSnapshot(session)
      .messages.filter((message) => message.role === "assistant")
      .map((message) => message.content),
  ).toEqual(["Full answer"]);
  expect(
    getSnapshot(session).messages.filter((message) => message.role === "user"),
  ).toHaveLength(1);
});
