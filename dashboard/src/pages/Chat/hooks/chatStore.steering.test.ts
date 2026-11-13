import { afterEach, describe, expect, it, vi } from "vitest";
import { getSnapshot, ingestHarnessChunk, removeSession } from "./chatStore";
import { parseHarnessChunk } from "../../../utils/parseHarnessChunk";
vi.mock("../../../i18n", () => ({ default: { t: (key: string) => key } }));
const session = "synthetic-steering";
afterEach(() => removeSession(session));
describe("steered turn projection", () => {
  it.each(["WebSocket", "SSE"])(
    "keeps an attachment-only %s insertion once with its canonical history identity",
    (transport) => {
      const chunk = {
        type: "user" as const,
        source: "dashboard_insert",
        command_id: "media",
        content: "",
        inbound_attachments: [
          {
            filename: "补充.png",
            workspace_path: "inbound/qa.png",
            kind: "image",
            resource_id: "res_qa",
            version: "a".repeat(64),
          },
        ],
      };
      const parsed =
        transport === "SSE"
          ? parseHarnessChunk("data: " + JSON.stringify(chunk))!
          : chunk;
      ingestHarnessChunk(session, parsed);
      ingestHarnessChunk(session, parsed);
      const users = getSnapshot(session).messages.filter(
        (m) => m.role === "user",
      );
      expect(users).toHaveLength(1);
      expect(users[0]).toMatchObject({
        id: "steer:media",
        content: "",
        attachments: [
          { filename: "补充.png", kind: "image", resourceId: "res_qa" },
        ],
      });
    },
  );
  it("closes an interrupted tool with a visible message and continues the inserted turn", () => {
    ingestHarnessChunk(session, {
      type: "tool_call_chunk",
      id: "call",
      name: "execute",
      args: '{"command":"sleep 900"}',
      index: 0,
      node: "agent",
    });
    ingestHarnessChunk(session, {
      type: "tool_call_chunk",
      id: "call-2",
      name: "execute",
      args: "{}",
      index: 1,
      node: "agent",
    });
    ingestHarnessChunk(session, {
      type: "tool_result",
      node: "tools",
      messages: [
        {
          type: "tool",
          tool_call_id: "call",
          content: "interrupted",
          status: "error",
          additional_kwargs: { octop_interrupted: true },
        },
        {
          type: "tool",
          tool_call_id: "call-2",
          content: "interrupted",
          status: "error",
          additional_kwargs: { octop_interrupted: true },
        },
      ],
    });
    ingestHarnessChunk(session, {
      type: "user",
      content: "now",
      command_id: "insert-now",
    });
    ingestHarnessChunk(session, {
      type: "token",
      node: "agent",
      content: "continuing",
    });
    const messages = getSnapshot(session).messages;
    const result = messages.find((m) => m.toolData?.callId === "call");
    expect(result?.status).toBe("error");
    expect(result?.toolData?.output).toBe("chat.steer.toolInterrupted");
    expect(
      messages.find((m) => m.toolData?.callId === "call-2")?.toolData?.output,
    ).toBe("chat.steer.toolInterrupted");
    expect(
      messages.filter((m) => m.role === "user").map((m) => m.content),
    ).toEqual(["now"]);
    expect(messages.at(-1)?.content).toBe("continuing");
  });
  it("keeps interrupted output before the inserted user and starts a new assistant bubble", () => {
    ingestHarnessChunk(session, {
      type: "run_phase",
      run_id: "run",
      phase: "llm_running",
    });
    ingestHarnessChunk(session, {
      type: "token",
      node: "agent",
      content: "partial",
    });
    ingestHarnessChunk(session, {
      type: "steering_applied",
      run_id: "run",
      command_id: "insert",
      phase: "llm_after",
      partial_output_retained: true,
    });
    ingestHarnessChunk(session, {
      type: "user",
      content: "direction",
      command_id: "insert",
    });
    ingestHarnessChunk(session, {
      type: "user",
      content: "direction",
      command_id: "insert",
    });
    ingestHarnessChunk(session, {
      type: "token",
      node: "agent",
      content: "new answer",
    });
    ingestHarnessChunk(session, { type: "done" });
    const messages = getSnapshot(session).messages;
    expect(messages.map((m) => [m.role, m.content])).toEqual([
      ["assistant", "partial"],
      ["user", "direction"],
      ["assistant", "new answer"],
    ]);
    expect(messages[0].metadata?.additional_kwargs?.octop_interrupted).toBe(
      true,
    );
  });
});

it("preserves the authenticated machine identity in the live store", () => {
  ingestHarnessChunk(session, {
    type: "user",
    command_id: "codex-input",
    content: "research",
    sender: { kind: "machine", id: "key", name: "Codex" },
  });
  expect(getSnapshot(session).messages[0].sender).toEqual({
    kind: "machine",
    id: "key",
    name: "Codex",
  });
});
