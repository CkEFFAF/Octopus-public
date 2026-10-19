import { afterEach, describe, expect, it } from "vitest";
import { getSnapshot, ingestHarnessChunk, removeSession } from "./chatStore";
const session = "synthetic-steering";
afterEach(() => removeSession(session));
describe("steered turn projection", () => {
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
