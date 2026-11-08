import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import AssistantTurnView from "./AssistantTurnView";
import type { ChatMessage } from "../hooks/useChat";
vi.mock("../../../context/AgentContext", () => ({
  useAgent: () => ({ activeAgentId: "main" }),
}));
vi.mock("./MessageBubble", () => ({
  default: ({ message }: { message: ChatMessage }) => (
    <div data-testid={message.hitlData ? "approval" : "answer"}>
      {message.content}
      {message.attachments?.map((file) => (
        <span key={file.url}>{file.filename}</span>
      ))}
    </div>
  ),
}));
vi.mock("./TurnProcessBlocks", () => ({
  TurnProcessBlocks: () => null,
  turnHasProcessSummary: () => false,
  turnHasVisibleProcess: () => false,
}));
it("places the delivered file after the conclusion", () => {
  render(
    <AssistantTurnView
      agentId="main"
      messages={[
        {
          id: "tool",
          role: "assistant",
          content: "",
          timestamp: 1,
          toolData: { name: "send_file", output: "" },
          attachments: [
            {
              kind: "file",
              filename: "report.md",
              url: "/api/agents/main/workspace/download?path=outbound%2Freport.md",
            },
          ],
        },
        {
          id: "answer",
          role: "assistant",
          content: "Conclusion first",
          status: "done",
          timestamp: 2,
        },
      ]}
    />,
  );
  const answer = screen.getByTestId("answer");
  const file = screen.getByRole("article", { name: "report.md" });
  expect(
    answer.compareDocumentPosition(file) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
});
it.each([true, false])(
  "retains attachments across an approval with conclusion=%s",
  (withConclusion) => {
    const before: ChatMessage = {
      id: "file",
      role: "assistant",
      content: "",
      timestamp: 1,
      attachments: [
        {
          kind: "file",
          filename: "before-approval.md",
          url: "/api/agents/main/workspace/download?path=outbound%2Fbefore-approval.md",
        },
      ],
    };
    const approval: ChatMessage = {
      id: "approval",
      role: "assistant",
      content: "Permission",
      timestamp: 2,
      hitlData: { status: "pending" } as ChatMessage["hitlData"],
    };
    const conclusion: ChatMessage = {
      id: "conclusion",
      role: "assistant",
      content: "Conclusion",
      timestamp: 3,
      status: "done",
    };
    render(
      <AssistantTurnView
        messages={[before, approval, ...(withConclusion ? [conclusion] : [])]}
      />,
    );
    expect(screen.getByText("before-approval.md")).toBeInTheDocument();
    if (withConclusion)
      expect(screen.getByTestId("answer")).toHaveTextContent("Conclusion");
  },
);
