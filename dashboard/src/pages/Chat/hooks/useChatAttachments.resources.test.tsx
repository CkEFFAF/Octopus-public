import { act, renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { uploadFile } from "../../../api/modules/upload";
import { useChatAttachments } from "./useChatAttachments";
import { extractAttachments } from "./useChat";
import { buildUserMessageContent } from "../utils/chatAttachments";

vi.mock("../../../api/modules/upload", () => ({ uploadFile: vi.fn() }));
vi.mock("../../../hooks/useServerUploadLimit", () => ({
  useServerUploadLimit: () => ({ maxUploadBytes: 100000, maxUploadMb: 1 }),
}));

it("keeps upload resource IDs through composer send content and restored history for PDF and vision input", async () => {
  vi.mocked(uploadFile).mockImplementation(async (_agent, file) => ({
    path: `inbound/${file.name}`,
    workspace_path: `inbound/${file.name}`,
    filename: file.name,
    media_type: file.type,
    url: "/api/upload",
    access_url: "/api/upload",
    resource_id: `resource-${file.name}`,
    version: `version-${file.name}`,
  }));
  const { result } = renderHook(() => useChatAttachments("parent"));
  await act(async () =>
    result.current.processFiles([
      new File(["paper"], "paper.pdf", { type: "application/pdf" }),
      new File(["figure"], "figure.png", { type: "image/png" }),
    ]),
  );
  const content = buildUserMessageContent("Review", result.current.attachments);
  expect(content).toMatchObject([
    { type: "text", text: "Review" },
    {
      type: "file",
      resource_id: "resource-paper.pdf",
      version: "version-paper.pdf",
    },
    {
      type: "image",
      resource_id: "resource-figure.png",
      version: "version-figure.png",
    },
  ]);
  expect(extractAttachments(content)).toMatchObject([
    { resourceId: "resource-paper.pdf", version: "version-paper.pdf" },
    { resourceId: "resource-figure.png", version: "version-figure.png" },
  ]);
});
