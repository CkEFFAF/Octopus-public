import { Blob as NativeBlob } from "node:buffer";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { request, requestBlob } from "../../../api/request";
import { executionApi } from "../../../api/modules/execution";
import type { CollaborationResource } from "../../../api/modules/collaboration";
import { useChatDockPanel } from "../hooks/useChatDockPanel";
import CollaborationPanel from "./CollaborationPanel";
import ChatDockPanel from "./ChatDockPanel";

vi.mock("../../../api/request", () => ({
  request: vi.fn(),
  requestBlob: vi.fn(),
}));
vi.mock("../../../api/modules/execution", () => ({
  executionApi: { createContext: vi.fn() },
}));
vi.mock("../../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "Asia/Shanghai",
}));
vi.mock("../../../components/DocumentPreviewCore", () => ({
  default: () => null,
}));
vi.mock("../../Agent/Workspace/components/CodeEditor", () => ({
  default: ({ value }: { value: string }) => <pre>{value}</pre>,
}));
vi.mock("../../../components/BrowserWorkspace", () => ({
  default: () => null,
}));
vi.mock("../../Agent/Workspace/components/WorkspaceDrawer", () => ({
  default: () => null,
}));
vi.mock("./ChatDockFileList", () => ({ default: () => null }));
vi.mock("./FilePanelContent", () => ({ default: () => null }));
vi.mock("./KnowledgeCitationPanelContent", () => ({ default: () => null }));
vi.mock("./ChatDockToolUiContent", () => ({ default: () => null }));
vi.mock("./ChatDockGit", () => ({ default: () => null }));
vi.mock("./ChatDockContext", () => ({ default: () => null }));
vi.mock("./ExecutionWorkbench", () => ({ default: () => null }));

const resource: CollaborationResource = {
  resource_id: "published-report",
  version: "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
  name: "Report.txt",
  media_type: "text/plain",
  size: 5,
  source_agent_id: "scientist",
  source_thread_id: "child",
  source_kind: "device",
  source_device_id: "gpu",
  parse_state: "ready",
  publication_state: "published",
  content_url: "",
  download_url: "",
  created_at: 1792285260,
};

/** Same panel → dock hook → real dock tab body composition as ChatPage. */
function ChatFixture() {
  const dock = useChatDockPanel(false, "parent", "root");
  return (
    <>
      <CollaborationPanel
        agentId="parent"
        threadId="root"
        onOpenResource={dock.openResource}
      />
      {dock.dockOpen && (
        <ChatDockPanel
          mode="right"
          onModeChange={dock.handleModeChange}
          onClose={dock.handleClose}
          agentId="parent"
          threadId="root"
          filePaths={[]}
          openTabs={dock.openTabs}
          activeTabId={dock.activeTabId}
          onSelectTab={dock.setActiveTab}
          onCloseTab={dock.closeTab}
          onOpenFile={dock.openFileAt}
        />
      )}
    </>
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

it("reaches verified report bytes from the parent panel using the real shared dock without starting execution", async () => {
  vi.stubGlobal(
    "URL",
    class extends URL {
      static createObjectURL = vi.fn(() => "blob:report");
      static revokeObjectURL = vi.fn();
    },
  );
  vi.mocked(request).mockImplementation(async (path) =>
    path.includes("/collaboration")
      ? {
          invocations: [],
          artifacts: [resource],
          events: [],
          next_cursor: 0,
          has_more: false,
        }
      : resource,
  );
  vi.mocked(requestBlob).mockResolvedValue(
    new NativeBlob(["hello"]) as unknown as Blob,
  );
  render(
    <MemoryRouter>
      <ChatFixture />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByRole("button", { name: /collaboration.title/ }));
  fireEvent.click(
    await screen.findByRole("button", { name: "common.preview" }),
  );
  // The real dock lazy-loads its preview; module transforms can exceed the
  // default one-second query timeout while the complete suite runs.
  expect(
    await screen.findByText("hello", {}, { timeout: 10000 }),
  ).toBeInTheDocument();
  expect(screen.getByRole("tab")).toHaveTextContent("Report.txt");
  expect(screen.getByRole("tab")).toHaveAttribute("aria-selected", "true");
  fireEvent.click(screen.getByRole("button", { name: "collaboration.title" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "common.preview" }),
  );
  await waitFor(() => expect(screen.getAllByRole("tab")).toHaveLength(1));
  expect(executionApi.createContext).not.toHaveBeenCalled();
  expect(requestBlob).toHaveBeenCalledWith(
    "/agents/parent/threads/root/resources/published-report/content",
  );
}, 15000);
