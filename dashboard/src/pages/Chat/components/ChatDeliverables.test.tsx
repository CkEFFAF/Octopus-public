import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import {
  collaborationApi,
  downloadCollaborationResource,
  verifiedResourceContent,
  type CollaborationResource,
} from "../../../api/modules/collaboration";
import { CollaborationProvider } from "../hooks/useCollaboration";
import ChatDeliverables from "./ChatDeliverables";

vi.mock("../../../api/modules/collaboration", () => ({
  collaborationApi: { list: vi.fn(), resource: vi.fn() },
  downloadCollaborationResource: vi.fn(),
  verifiedResourceContent: vi.fn(),
}));
afterEach(() => vi.restoreAllMocks());
const resource: CollaborationResource = {
  resource_id: "res-zip",
  version: "a".repeat(64),
  name: "result.zip",
  media_type: "application/zip",
  size: 35952,
  source_agent_id: "child",
  source_thread_id: "child-thread",
  source_kind: "device",
  source_device_id: "laptop",
  parse_state: "pending",
  publication_state: "published",
  content_url: "https://untrusted.example/a",
  download_url: "https://untrusted.example/b",
  created_at: 1,
};

it("shows child expert deliveries inline and uses the root authorized scope", async () => {
  vi.mocked(collaborationApi.list).mockResolvedValue({
    invocations: [],
    events: [],
    artifacts: [
      resource,
      {
        ...resource,
        resource_id: "uploaded",
        source_kind: "upload",
        name: "input.pdf",
      },
      {
        ...resource,
        resource_id: "failed",
        publication_state: "unavailable",
        name: "failed.zip",
      },
    ],
    next_cursor: 1,
    has_more: false,
  });
  const open = vi.fn();
  render(
    <CollaborationProvider agentId="parent" threadId="root">
      <ChatDeliverables agentId="parent" threadId="root" onOpen={open} />
    </CollaborationProvider>,
  );
  expect(await screen.findByText("result.zip")).toBeInTheDocument();
  expect(screen.queryByText("input.pdf")).not.toBeInTheDocument();
  expect(screen.queryByText("failed.zip")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("common.preview"));
  expect(open).toHaveBeenCalledWith(resource);
  fireEvent.click(screen.getByText("common.download"));
  await waitFor(() =>
    expect(downloadCollaborationResource).toHaveBeenCalledWith(
      "parent",
      "root",
      resource,
    ),
  );
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});

it("fetches image metadata and verified bytes rather than the producer's workspace", async () => {
  const picture = {
    ...resource,
    resource_id: "picture",
    name: "figure.png",
    media_type: "image/png",
  };
  vi.mocked(collaborationApi.list).mockResolvedValue({
    invocations: [],
    events: [],
    artifacts: [picture],
    next_cursor: 1,
    has_more: false,
  });
  vi.mocked(collaborationApi.resource).mockResolvedValue(picture);
  vi.mocked(verifiedResourceContent).mockResolvedValue(
    new Blob(["image"], { type: "image/png" }),
  );
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:verified");
  const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  const open = vi.fn();
  const { unmount } = render(
    <CollaborationProvider agentId="parent" threadId="root">
      <ChatDeliverables agentId="parent" threadId="root" onOpen={open} />
    </CollaborationProvider>,
  );
  expect(await screen.findByRole("img")).toHaveAttribute(
    "src",
    "blob:verified",
  );
  expect(verifiedResourceContent).toHaveBeenCalledWith(
    "parent",
    "root",
    picture,
  );
  fireEvent.click(screen.getByText("common.preview"));
  const dialog = await screen.findByRole("dialog");
  expect(dialog.querySelector("img")).toHaveAttribute("src", "blob:verified");
  expect(open).not.toHaveBeenCalled();
  unmount();
  expect(revoke).toHaveBeenCalledWith("blob:verified");
});
