import { describe, expect, it } from "vitest";
import type { ChatMessage } from "../hooks/useChat";
import { findScheduleMessage } from "./scheduleMessage";

const message = (
  id: string,
  timestamp: number,
  content = "Training finished",
) => ({ id, role: "assistant", timestamp, content }) as ChatMessage;
describe("scheduled result message positioning", () => {
  it("finds this execution rather than identical output from an earlier run", () => {
    const rows = [
      message("old", 1000),
      message("target", 15000),
      message("later", 25000),
    ];
    expect(
      findScheduleMessage(rows, {
        threadId: "t",
        after: 14000,
        before: 16000,
        excerpt: "Training finished",
      })?.id,
    ).toBe("target");
  });
  it("ignores whitespace differences and never jumps to unrelated output", () => {
    expect(
      findScheduleMessage([message("target", 15000, "Training\nfinished")], {
        threadId: "t",
        after: 14000,
        before: 16000,
        excerpt: "Training finished",
      })?.id,
    ).toBe("target");
    expect(
      findScheduleMessage([message("unrelated", 15000, "Other task")], {
        threadId: "t",
        after: 14000,
        before: 16000,
        excerpt: "Training finished",
      }),
    ).toBeUndefined();
  });
});
