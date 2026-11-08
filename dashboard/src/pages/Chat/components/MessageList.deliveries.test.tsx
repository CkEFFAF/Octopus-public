import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ChatMessage } from "../hooks/useChat";
import { CollaborationProvider } from "../hooks/useCollaboration";
import {
  collaborationApi,
  type CollaborationResource,
} from "../../../api/modules/collaboration";
import MessageList from "./MessageList";
vi.mock("../../../context/AgentContext", () => ({
  useAgent: () => ({ activeAgentId: "host", agents: [] }),
}));
vi.mock("../../../api/modules/collaboration", () => ({
  collaborationApi: { list: vi.fn() },
}));
vi.mock("../hooks/useAutoScroll", () => ({
  useAutoScroll: () => ({
    showScrollBtn: false,
    scrollToBottom: () => {},
    armProgrammaticGuard: () => {},
    handleAtBottomChange: () => {},
  }),
}));
vi.mock("./TurnTimelineRail", () => ({ default: () => null }));
vi.mock("./GeneratingIndicator", () => ({ default: () => null }));
vi.mock("./MessageBubble", () => ({
  default: ({ message }: { message: ChatMessage }) => <p>{message.content}</p>,
}));
vi.mock("./TurnProcessBlocks", () => ({
  TurnProcessBlocks: () => null,
  turnHasVisibleProcess: () => false,
  turnHasProcessSummary: () => false,
}));
const message = (
  id: string,
  role: ChatMessage["role"],
  timestamp: number,
): ChatMessage => ({ id, role, timestamp, content: id });
it("renders a delivery after its original answer, rather than after a later user question", async () => {
  vi.mocked(collaborationApi.list).mockResolvedValue({
    artifacts: [
      {
        resource_id: "report",
        version: "v",
        source_agent_id: "host",
        source_thread_id: "thread",
        source_kind: "workspace",
        name: "report.md",
        media_type: "text/markdown",
        size: 20,
        publication_state: "published",
        created_at: 2,
      } as CollaborationResource,
    ],
    invocations: [],
    events: [],
    has_more: false,
    next_cursor: 1,
  });
  render(
    <CollaborationProvider agentId="host" threadId="thread">
      <MessageList
        agentId="host"
        sessionKey="thread"
        deliveryScope={{ agentId: "host", threadId: "thread" }}
        messages={[
          message("question-one", "user", 1000),
          message("answer-one", "assistant", 3000),
          message("question-two", "user", 5000),
          message("answer-two", "assistant", 6000),
        ]}
      />
    </CollaborationProvider>,
  );
  const card = await screen.findByTitle("report.md");
  expect(card.closest("[data-message-id]")).toHaveAttribute(
    "data-message-id",
    "answer-one",
  );
  expect(
    screen.getByText("answer-one").compareDocumentPosition(card) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    card.compareDocumentPosition(screen.getByText("question-two")) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
});
