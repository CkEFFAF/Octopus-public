import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import ChatDockFileList from "./ChatDockFileList";

vi.mock("../ChatFilePreviewContext", () => ({
  useChatFileChanges: () => ({
    history: [],
    current: [],
    threadId: "conversation-b",
  }),
}));
vi.mock("./FileChangesReview", () => ({
  default: () => <div data-testid="file-review" />,
}));
vi.mock("../../../components/PinnedFilesPanel", () => ({
  default: ({ agentId, threadId }: { agentId: string; threadId: string }) => (
    <div data-testid="pinned-files">
      {agentId}:{threadId}
    </div>
  ),
}));

it("retains the expert's pinned files above the conversation's file review", () => {
  render(
    <ChatDockFileList agentId="gpu" filePaths={[]} onOpenFile={vi.fn()} />,
  );
  expect(screen.getByTestId("pinned-files")).toHaveTextContent(
    "gpu:conversation-b",
  );
  expect(screen.getByTestId("file-review")).toBeInTheDocument();
});
