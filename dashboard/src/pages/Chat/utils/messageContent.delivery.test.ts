import { expect, it } from "vitest";
import { splitAssistantTurn } from "./messageContent";
import type { ChatMessage } from "../hooks/useChat";
const file = {
  kind: "file" as const,
  url: "/api/agents/main/workspace/download?path=outbound%2Freport.md",
  filename: "report.md",
};
const message = (
  id: string,
  content: string,
  extra: Partial<ChatMessage> = {},
): ChatMessage => ({
  id,
  role: "assistant",
  content,
  status: "done",
  timestamp: 1,
  ...extra,
});
it("keeps an attachment-only assistant answer", () => {
  expect(
    splitAssistantTurn([message("only", "", { attachments: [file] })])
      .answerMessage,
  ).toMatchObject({ id: "only", content: "", attachments: [file] });
});
it("retains and deduplicates earlier attachments with the final conclusion", () => {
  const split = splitAssistantTurn([
    message("early", "working", { attachments: [file] }),
    message("tool", "", { toolData: { name: "execute", output: "done" } }),
    message("final", "conclusion", { attachments: [file] }),
  ]);
  expect(split.answerMessage).toMatchObject({
    id: "final",
    content: "conclusion",
    attachments: [file],
  });
});
it("leaves tool attachments in the tool strip", () => {
  const split = splitAssistantTurn([
    message("tool", "", {
      toolData: { name: "send_file" },
      attachments: [file],
    }),
    message("final", "conclusion"),
  ]);
  expect(split.answerMessage?.attachments).toBeUndefined();
  expect(split.tools[0].attachments).toEqual([file]);
});
