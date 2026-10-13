import { describe, expect, it } from "vitest";
import { chatAnimationPhase, toolAnimationPhase } from "./expertAnimation";
import type { ChatMessage } from "../hooks/sseHelpers";
const msg = (extra: Partial<ChatMessage>): ChatMessage => ({
  id: "m",
  role: "assistant",
  content: "",
  timestamp: 1,
  ...extra,
});
describe("real conversation animation states", () => {
  it.each([
    ["web_search", "searching"],
    ["read_file", "reading"],
    ["apply_patch", "coding"],
    ["write_todos", "planning"],
    ["image_gen", "drawing"],
    ["ask_agent", "collaborating"],
    ["upload_file", "uploading"],
    ["download_file", "downloading"],
    ["execute", "running"],
    ["analyze_data", "analyzing"],
    ["check_tests", "verifying"],
    ["handoff", "handoff"],
  ])("maps %s to %s", (tool, phase) =>
    expect(toolAnimationPhase(tool)).toBe(phase),
  );
  it("gives unresolved approvals priority over running tools", () => {
    const messages = [
      msg({ role: "user" }),
      msg({ toolData: { name: "execute" } }),
      msg({
        hitlData: { pending_id: "p", action_requests: [{ name: "execute" }] },
      }),
    ];
    expect(chatAnimationPhase(messages, true)).toBe("waiting_permission");
    messages[2].hitlData!.action_requests = [{ name: "ask_user_question" }];
    expect(chatAnimationPhase(messages, false)).toBe("waiting_user");
  });
  it("ignores old failures and permissions when a new user turn starts", () => {
    expect(
      chatAnimationPhase(
        [
          msg({ status: "error" }),
          msg({ hitlData: { action_requests: [{ name: "execute" }] } }),
          msg({ role: "user", id: "new" }),
        ],
        true,
      ),
    ).toBe("thinking");
  });
  it("distinguishes reasoning, speech, failure and idle history", () => {
    expect(
      chatAnimationPhase([msg({ type: "reasoning", content: "reason" })], true),
    ).toBe("thinking");
    expect(
      chatAnimationPhase(
        [msg({ content: "answer", status: "streaming" })],
        true,
      ),
    ).toBe("speaking");
    expect(chatAnimationPhase([msg({ status: "error" })], false)).toBe("error");
    expect(
      chatAnimationPhase(
        [msg({ content: "old answer", status: "done" })],
        false,
      ),
    ).toBe("idle");
  });
});
