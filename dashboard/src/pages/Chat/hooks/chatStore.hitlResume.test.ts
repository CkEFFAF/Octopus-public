import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getSnapshot,
  ingestHarnessChunk,
  removeSession,
  resumeHitl,
  setMessages,
} from "./chatStore";

vi.mock("../../../api/config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
}));

const SESSION = "test-hitl-resume";

describe("resumeHitl", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    removeSession(SESSION);
  });

  it("renders resumed tokens and notifies after the completed stream", async () => {
    const body = [
      'event: chunk\ndata: {"type":"token","content":"completed answer"}\n\n',
      'event: chunk\ndata: {"type":"done"}\n\n',
    ].join("");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(body, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      ),
    );
    const onStreamEnd = vi.fn();

    await resumeHitl(
      SESSION,
      "agent-1",
      "thread-1",
      [{ type: "respond", message: "answer" }],
      onStreamEnd,
    );

    expect(getSnapshot(SESSION).messages.at(-1)?.content).toBe(
      "completed answer",
    );
    expect(getSnapshot(SESSION).isStreaming).toBe(false);
    expect(onStreamEnd).toHaveBeenCalledOnce();
  });

  it("deduplicates the same resumed event arriving on WebSocket and SSE", async () => {
    const chunk = {
      type: "token" as const,
      content: "once",
      event_id: "resume:one:1",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async () => {
        ingestHarnessChunk(SESSION, chunk);
        return new Response(
          `data: ${JSON.stringify(
            chunk,
          )}\n\ndata: {"type":"done","event_id":"resume:one:2"}\n\n`,
          { status: 200 },
        );
      }),
    );
    await resumeHitl(SESSION, "agent", "thread", [{ type: "approve" }]);
    expect(getSnapshot(SESSION).messages.at(-1)?.content).toBe("once");
  });

  it("does not let an old SSE close the next queued run", async () => {
    const phase = {
      type: "run_phase" as const,
      run_id: "A",
      phase: "llm_running",
      event_id: "resume:A:1",
    };
    const token = {
      type: "token" as const,
      content: "answer A",
      event_id: "resume:A:2",
    };
    const done = { type: "done" as const, event_id: "resume:A:3" };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async () => {
        for (const chunk of [phase, token, done])
          ingestHarnessChunk(SESSION, chunk);
        ingestHarnessChunk(SESSION, {
          type: "user",
          content: "queued B",
          command_id: "queue-B",
        });
        ingestHarnessChunk(SESSION, {
          type: "run_phase",
          run_id: "B",
          phase: "llm_running",
        });
        ingestHarnessChunk(SESSION, { type: "token", content: "answer B" });
        return new Response(
          [phase, token, done]
            .map((chunk) => `data: ${JSON.stringify(chunk)}\n\n`)
            .join(""),
        );
      }),
    );
    await resumeHitl(SESSION, "agent", "thread", [{ type: "approve" }]);
    expect(getSnapshot(SESSION).isStreaming).toBe(true);
    expect(
      getSnapshot(SESSION).messages.map((message) => message.content),
    ).toEqual(["answer A", "queued B", "answer B"]);
    expect(getSnapshot(SESSION).messages.at(-1)?.status).toBe("streaming");
  });

  it.each([false, true])(
    "does not replay a delayed stream longer than the event window (next run: %s)",
    async (nextRun) => {
      const phase = {
        type: "run_phase" as const,
        run_id: "long-A",
        phase: "llm_running",
        event_id: "resume:long:1",
      };
      const tokens = Array.from({ length: 2200 }, (_, index) => ({
        type: "token" as const,
        content: `${index};`,
        event_id: `resume:long:${index + 2}`,
      }));
      const done = { type: "done" as const, event_id: "resume:long:2202" };
      const chunks = [phase, ...tokens, done];
      vi.stubGlobal(
        "fetch",
        vi.fn().mockImplementation(async () => {
          for (const chunk of chunks) ingestHarnessChunk(SESSION, chunk);
          if (nextRun) {
            ingestHarnessChunk(SESSION, {
              type: "user",
              content: "queued B",
              command_id: "queue-B",
            });
            ingestHarnessChunk(SESSION, {
              type: "run_phase",
              run_id: "B",
              phase: "llm_running",
            });
            ingestHarnessChunk(SESSION, { type: "token", content: "answer B" });
          }
          return new Response(
            chunks
              .map((chunk) => `data: ${JSON.stringify(chunk)}\n\n`)
              .join(""),
          );
        }),
      );
      await resumeHitl(SESSION, "agent", "thread", [{ type: "approve" }]);
      expect(getSnapshot(SESSION).isStreaming).toBe(nextRun);
      expect(
        getSnapshot(SESSION).messages.map((message) => message.content),
      ).toEqual(
        nextRun
          ? [
              tokens.map((token) => token.content).join(""),
              "queued B",
              "answer B",
            ]
          : [tokens.map((token) => token.content).join("")],
      );
    },
  );

  it("records the session policy on the resolved card", async () => {
    setMessages(SESSION, [
      {
        id: "hitl",
        role: "assistant",
        content: "",
        timestamp: 0,
        status: "done",
        hitlData: {
          action_requests: [{ name: "execute", args: {} }],
          status: "pending",
        },
      },
    ]);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response('event: chunk\ndata: {"type":"done"}\n\n', {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      ),
    );

    await resumeHitl(
      SESSION,
      "agent-1",
      "thread-1",
      [{ type: "approve" }],
      undefined,
      false,
      { mode: "allow_all" },
    );

    expect(getSnapshot(SESSION).messages[0]?.hitlData?.status).toBe("approved");
    expect(getSnapshot(SESSION).messages[0]?.hitlData?.resolution).toBe(
      "allow_all",
    );
  });

  it("does not rewrite already resolved HITL cards", async () => {
    setMessages(SESSION, [
      {
        id: "old",
        role: "assistant",
        content: "",
        timestamp: 0,
        status: "done",
        hitlData: {
          action_requests: [{ name: "write_file", args: {} }],
          status: "approved",
          resolution: "approve",
        },
      },
      {
        id: "pending",
        role: "assistant",
        content: "",
        timestamp: 1,
        status: "done",
        hitlData: {
          action_requests: [{ name: "execute", args: {} }],
          status: "pending",
        },
      },
    ]);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response('event: chunk\ndata: {"type":"done"}\n\n', {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      ),
    );

    await resumeHitl(
      SESSION,
      "agent-1",
      "thread-1",
      [{ type: "approve" }],
      undefined,
      false,
      { mode: "allow_all" },
    );

    const messages = getSnapshot(SESSION).messages;
    expect(messages[0]?.hitlData).toMatchObject({
      status: "approved",
      resolution: "approve",
    });
    expect(messages[1]?.hitlData).toMatchObject({
      status: "approved",
      resolution: "allow_all",
    });
  });
});
