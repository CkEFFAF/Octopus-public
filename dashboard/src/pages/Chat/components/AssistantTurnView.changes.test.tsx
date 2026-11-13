import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ChatMessage } from "../hooks/useChat";
import AssistantTurnView from "./AssistantTurnView";

vi.mock("../../../context/AgentContext", () => ({
  useAgent: () => ({ activeAgentId: "host" }),
}));
vi.mock("./MessageBubble", () => ({ default: () => null }));
vi.mock("./ToolMediaStrip", () => ({ ToolMediaStrip: () => null }));
vi.mock("./TurnProcessBlocks", () => ({
  TurnProcessBlocks: () => null,
  turnHasVisibleProcess: () => false,
  turnHasProcessSummary: () => false,
}));
const edit = (id: string, path: string): ChatMessage => ({
  id,
  role: "assistant",
  timestamp: 1,
  content: "",
  status: "done",
  toolData: {
    name: "edit_file",
    arguments: JSON.stringify({
      file_path: path,
      old_string: `old ${id}`,
      new_string: `new ${id}`,
    }),
    output: '{"occurrences":1}',
  },
});
it("opens only the clicked answer's changes and keeps later edits live in its modal", async () => {
  const first = [edit("first", "earlier.py"), edit("second", "shared.py")];
  const current = [edit("current", "shared.py")];
  const view = render(
    <>
      <AssistantTurnView messages={first} />
      <AssistantTurnView messages={current} />
    </>,
  );
  fireEvent.click(
    screen.getAllByRole("button", { name: "chat.editFileCard" })[1],
  );
  const modal = await screen.findByRole("dialog");
  expect(
    within(within(modal).getByRole("navigation")).getByText("shared.py"),
  ).toBeInTheDocument();
  expect(within(modal).queryByText("earlier.py")).not.toBeInTheDocument();
  expect(within(modal).getByText("old current")).toBeInTheDocument();
  expect(within(modal).queryByText("old second")).not.toBeInTheDocument();
  view.rerender(
    <>
      <AssistantTurnView messages={first} />
      <AssistantTurnView messages={[...current, edit("later", "shared.py")]} />
    </>,
  );
  expect(within(modal).getByText("new later")).toBeInTheDocument();
});
