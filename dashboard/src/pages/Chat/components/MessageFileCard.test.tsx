import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { requestBlob } from "../../../api/request";
import { downloadAuthFile } from "../../../components/AuthFileDownloadLink";
import { ChatFilePreviewProvider } from "../ChatFilePreviewContext";
import ChatDockFileList from "./ChatDockFileList";
import { MessageFileCard } from "./MessageFileCard";

vi.mock("../../../components/AuthFileDownloadLink", () => ({
  downloadAuthFile: vi.fn().mockResolvedValue(undefined),
}));
vi.mock("../../../api/request", () => ({ requestBlob: vi.fn() }));

beforeEach(() => vi.clearAllMocks());

describe("delivered expert file sources", () => {
  const path = "outbound/main_en_文件报告.md";
  const url = `/api/agents/main/workspace/download?path=${encodeURIComponent(
    path,
  )}`;

  it("preserves expert storage on preview and the original URL on download", async () => {
    const open = vi.fn();
    render(
      <ChatFilePreviewProvider
        openFilePreview={open}
        openKnowledgeCitation={vi.fn()}
      >
        <MessageFileCard
          url={url}
          filename="main_en_文件报告.md"
          agentId="main"
        />
      </ChatFilePreviewProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "common.preview" }));
    expect(open).toHaveBeenCalledWith(path, "main", "workspace");
    fireEvent.click(screen.getByRole("button", { name: "common.download" }));
    await waitFor(() =>
      expect(downloadAuthFile).toHaveBeenCalledWith(url, {
        filename: "main_en_文件报告.md",
      }),
    );
  });

  it("downloads explicit expert paths from the file list", async () => {
    const open = vi.fn();
    const createUrl = vi.fn().mockReturnValue("blob:test");
    const revokeUrl = vi.fn();
    vi.stubGlobal(
      "URL",
      class extends URL {
        static createObjectURL = createUrl;
        static revokeObjectURL = revokeUrl;
      },
    );
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    vi.mocked(requestBlob).mockResolvedValue(new Blob(["report"]));
    try {
      render(
        <ChatDockFileList
          agentId="main"
          filePaths={[
            {
              path: `/.agent/${path}`,
              agentId: "main",
            },
          ]}
          onOpenFile={open}
        />,
      );
      fireEvent.click(screen.getByText("main_en_文件报告.md"));
      expect(open).toHaveBeenCalledWith(`/.agent/${path}`, "main");
      fireEvent.click(screen.getByRole("button", { name: "下载" }));
      await waitFor(() =>
        expect(requestBlob).toHaveBeenCalledWith(
          `/agents/main/workspace/download?path=${encodeURIComponent(path)}`,
        ),
      );
      await waitFor(() => expect(click).toHaveBeenCalledOnce());
      expect(revokeUrl).toHaveBeenCalledWith("blob:test");
    } finally {
      click.mockRestore();
      vi.unstubAllGlobals();
    }
  });
});
