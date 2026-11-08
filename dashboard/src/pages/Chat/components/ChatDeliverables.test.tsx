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
vi.mock("./ResourcePanelContent", () => ({
  default: ({
    agentId,
    threadId,
    resourceId,
  }: {
    agentId: string;
    threadId: string;
    resourceId: string;
  }) => (
    <output aria-label="Scoped resource preview">
      {agentId}|{threadId}|{resourceId}
    </output>
  ),
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
  render(
    <CollaborationProvider agentId="parent" threadId="root">
      <ChatDeliverables agentId="parent" threadId="root" />
    </CollaborationProvider>,
  );
  expect(await screen.findByTitle("result.zip")).toBeInTheDocument();
  expect(screen.queryByTitle("input.pdf")).not.toBeInTheDocument();
  expect(screen.queryByTitle("failed.zip")).not.toBeInTheDocument();
  expect(screen.queryByText("common.preview")).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "chat.deliverables.open" }),
  );
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  expect(
    await screen.findByLabelText("Scoped resource preview"),
  ).toHaveTextContent("parent|root|res-zip");
  fireEvent.click(
    screen.getByRole("button", { name: "chat.flow.downloadFile" }),
  );
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
  const { unmount } = render(
    <CollaborationProvider agentId="parent" threadId="root">
      <ChatDeliverables agentId="parent" threadId="root" />
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
  fireEvent.click(
    screen.getAllByRole("button", { name: "chat.deliverables.open" })[0],
  );
  const dialog = await screen.findByRole("dialog");
  expect(dialog.querySelector("img")).toHaveAttribute("src", "blob:verified");
  expect(
    screen.queryByLabelText("Scoped resource preview"),
  ).not.toBeInTheDocument();
  unmount();
  expect(revoke).toHaveBeenCalledWith("blob:verified");
});

it("bounds a large collection with type and more-file controls, without search", async () => {
  const artifacts = Array.from({ length: 12 }, (_, index) => ({
    ...resource,
    resource_id: `file-${index}`,
    name:
      index < 4
        ? `bundle-${index}.zip`
        : index < 8
        ? `data-${index - 4}.csv`
        : `report-${index - 8}.pdf`,
    media_type:
      index < 4
        ? "application/zip"
        : index < 8
        ? "text/csv"
        : "application/pdf",
    created_at: index,
  }));
  vi.mocked(collaborationApi.list).mockResolvedValue({
    invocations: [],
    events: [],
    artifacts,
    next_cursor: 1,
    has_more: false,
  });
  render(
    <CollaborationProvider agentId="parent" threadId="root">
      <ChatDeliverables agentId="parent" threadId="root" />
    </CollaborationProvider>,
  );
  await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(6));
  fireEvent.click(
    screen.getByRole("button", { name: /chat.deliverables.types.data/ }),
  );
  expect(screen.getAllByRole("article")).toHaveLength(4);
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: /chat.deliverables.types.all/ }),
  );
  fireEvent.click(screen.getByText("chat.deliverables.more"));
  expect(screen.getAllByRole("article")).toHaveLength(12);
  fireEvent.click(screen.getByText("chat.deliverables.collapse"));
  expect(screen.getAllByRole("article")).toHaveLength(6);
});

it("does not fetch image bytes for cards beyond the visible page", async () => {
  const artifacts = Array.from({ length: 20 }, (_, index) => ({
    ...resource,
    resource_id: `image-${index}`,
    name: `image-${index}.png`,
    media_type: "image/png",
    created_at: index,
  }));
  vi.mocked(collaborationApi.list).mockResolvedValue({
    invocations: [],
    events: [],
    artifacts,
    next_cursor: 1,
    has_more: false,
  });
  vi.mocked(collaborationApi.resource)
    .mockClear()
    .mockImplementation(
      async (_agent, _thread, id) =>
        artifacts.find((item) => item.resource_id === id)!,
    );
  vi.mocked(verifiedResourceContent).mockResolvedValue(
    new Blob(["PNG"], { type: "image/png" }),
  );
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:visible-image");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  render(
    <CollaborationProvider agentId="parent" threadId="root">
      <ChatDeliverables agentId="parent" threadId="root" />
    </CollaborationProvider>,
  );
  await waitFor(() =>
    expect(collaborationApi.resource).toHaveBeenCalledTimes(6),
  );
  fireEvent.click(screen.getByText("chat.deliverables.more"));
  await waitFor(() =>
    expect(collaborationApi.resource).toHaveBeenCalledTimes(12),
  );
});

it("keeps active filters clearable after published files are withdrawn", async () => {
  const artifacts = Array.from({ length: 8 }, (_, index) => ({
    ...resource,
    resource_id: `file-${index}`,
    name: index === 0 ? "metrics.csv" : `bundle-${index}.zip`,
    media_type: index === 0 ? "text/csv" : "application/zip",
  }));
  vi.mocked(collaborationApi.list)
    .mockResolvedValueOnce({
      invocations: [],
      events: [],
      artifacts,
      next_cursor: 1,
      has_more: false,
    })
    .mockResolvedValue({
      invocations: [],
      events: [],
      artifacts: artifacts.map((item, index) => ({
        ...item,
        publication_state: index < 3 ? "unavailable" : "published",
      })),
      next_cursor: 2,
      has_more: false,
    });
  render(
    <CollaborationProvider agentId="parent" threadId="root">
      <ChatDeliverables agentId="parent" threadId="root" />
    </CollaborationProvider>,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: /chat.deliverables.types.data/ }),
  );
  fireEvent.click(screen.getByRole("button", { name: "common.refresh" }));
  await screen.findByText("chat.deliverables.noMatch");
  expect(
    screen.getByRole("button", { name: /chat.deliverables.types.data/ }),
  ).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(
    screen.getByRole("button", { name: /chat.deliverables.types.all/ }),
  );
  expect(screen.getAllByRole("article")).toHaveLength(5);
});
