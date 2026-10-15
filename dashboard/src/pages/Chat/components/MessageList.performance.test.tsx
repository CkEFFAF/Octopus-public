import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatMessage } from "../hooks/useChat";
import * as fileDetection from "../hooks/useChatFileDetection";
import * as knowledgeParser from "../../../utils/parseKnowledgeCitations";
import MessageList from "./MessageList";

vi.mock("../../../context/AgentContext", () => ({
  useAgent: () => ({ activeAgentId: "host", agents: [] }),
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
  default: ({
    message,
    onRegenerate,
  }: {
    message: ChatMessage;
    onRegenerate?: (id: string) => void;
  }) => (
    <button onClick={() => onRegenerate?.(message.id)}>
      {message.content}
    </button>
  ),
}));
vi.mock("./TurnProcessBlocks", () => ({
  TurnProcessBlocks: () => null,
  turnHasVisibleProcess: () => false,
  turnHasProcessSummary: () => false,
}));
vi.mock("./ToolMediaStrip", () => ({ ToolMediaStrip: () => null }));

function message(
  id: string,
  role: ChatMessage["role"],
  content = "",
): ChatMessage {
  return {
    id,
    role,
    content,
    timestamp: 1,
    status: "done",
    speakerAgentId: "host",
  };
}

function largeTools(prefix: string, count: number): ChatMessage[] {
  const output = JSON.stringify({ log: "long tool result ".repeat(4096) });
  return Array.from({ length: count }, (_, i) => ({
    ...message(`${prefix}-${i}`, "assistant"),
    toolData: {
      name:
        i % 30 === 0
          ? "search_knowledge"
          : i % 30 === 1
          ? "write_todos"
          : "read_file",
      arguments: "{}",
      output,
    },
  }));
}

afterEach(() => vi.restoreAllMocks());

describe("message list streaming work", () => {
  it("does not reprocess completed turns when new tokens arrive", () => {
    const history = [
      message("old-user", "user", "old question"),
      ...largeTools("old-tool", 120),
      message("old-answer", "assistant", "completed answer"),
      message("single-user", "user", "short question"),
      message("single-answer", "assistant", "short completed answer"),
      message("new-user", "user", "new question"),
    ];
    const collect = vi.spyOn(fileDetection, "collectChatFilePaths");
    const props = { agentId: "host", isStreaming: true, onRegenerate: vi.fn() };
    const { rerender } = render(
      <MessageList
        {...props}
        liveSpeakers={["host"]}
        messages={[
          ...history,
          { ...message("live", "assistant", "token"), status: "streaming" },
        ]}
      />,
    );
    collect.mockClear();
    const start = performance.now();
    for (let i = 0; i < 5; i++) {
      rerender(
        <MessageList
          {...props}
          liveSpeakers={["host"]}
          messages={[
            ...history,
            {
              ...message("live", "assistant", `token ${i}`),
              status: "streaming",
            },
          ]}
        />,
      );
    }
    const completedRecalculations = collect.mock.calls.filter(([turn]) =>
      turn.some((m) => m.id === "old-answer" || m.id === "single-answer"),
    ).length;
    console.info("history stream benchmark", {
      tools: 120,
      updates: 5,
      completedRecalculations,
      elapsedMs: performance.now() - start,
    });
    expect(screen.getByRole("button", { name: "token 4" })).toBeInTheDocument();
    expect(completedRecalculations).toBe(0);

    const updatedRegenerate = vi.fn();
    rerender(
      <MessageList
        {...props}
        onRegenerate={updatedRegenerate}
        messages={[...history, message("live", "assistant", "finished")]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "completed answer" }));
    expect(updatedRegenerate).toHaveBeenCalledWith("old-answer");
    const changedHistory = history.map((m) =>
      m.id === "old-answer" ? { ...m, content: "corrected answer" } : m,
    );
    rerender(
      <MessageList
        {...props}
        messages={[...changedHistory, message("live", "assistant", "finished")]}
      />,
    );
    expect(
      screen.getByRole("button", { name: "corrected answer" }),
    ).toBeInTheDocument();
  });

  it("does not parse settled large tool results again within a growing turn", () => {
    const tools = largeTools("tool", 120);
    const output = tools[0].toolData!.output!;
    const parse = vi.spyOn(JSON, "parse");
    const parseCitations = vi.spyOn(knowledgeParser, "parseKnowledgeCitations");
    const props = { agentId: "host", isStreaming: true, compactProcess: true };
    const { rerender } = render(
      <MessageList
        {...props}
        messages={[
          ...tools,
          { ...message("live", "assistant", "token"), status: "streaming" },
        ]}
      />,
    );
    parse.mockClear();
    parseCitations.mockClear();
    const start = performance.now();
    for (let i = 0; i < 5; i++) {
      rerender(
        <MessageList
          {...props}
          messages={[
            ...tools,
            {
              ...message("live", "assistant", `token ${i}`),
              status: "streaming",
            },
          ]}
        />,
      );
    }
    const repeatedOutputParses = parse.mock.calls.filter(
      ([raw]) => raw === output,
    ).length;
    console.info("large turn stream benchmark", {
      tools: 120,
      outputBytes: output.length,
      updates: 5,
      repeatedOutputParses,
      elapsedMs: performance.now() - start,
    });
    expect(repeatedOutputParses).toBe(0);
    expect(parseCitations).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "token 4" })).toBeInTheDocument();

    const updatedTools = tools.map((tool, index) => {
      if (index === 0) {
        return {
          ...tool,
          toolData: {
            ...tool.toolData!,
            output:
              'passages\n<!--octop-kb-citations:[{"doc_id":"changed","filename":"updated-citation.md"}]-->',
          },
        };
      }
      if (index === 1) {
        return {
          ...tool,
          toolData: {
            ...tool.toolData!,
            output:
              '{"todos":[{"id":"1","content":"updated task","status":"completed"}]}',
          },
        };
      }
      return tool;
    });
    rerender(
      <MessageList
        {...props}
        messages={[...updatedTools, message("live", "assistant", "finished")]}
      />,
    );
    expect(screen.getByText("updated task")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "updated-citation.md" }),
    ).toBeInTheDocument();
  });
});
