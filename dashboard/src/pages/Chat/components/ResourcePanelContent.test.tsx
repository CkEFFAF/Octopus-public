import { Blob as NativeBlob } from "node:buffer";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { request, requestBlob } from "../../../api/request";
import type { CollaborationResource } from "../../../api/modules/collaboration";
import ResourcePanelContent from "./ResourcePanelContent";

vi.mock("../../../api/request", () => ({
  request: vi.fn(),
  requestBlob: vi.fn(),
}));
vi.mock("../../../components/DocumentPreviewCore", () => ({
  default: () => <p>Document renderer</p>,
}));
const resource: CollaborationResource = {
  resource_id: "opaque/report",
  version: "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
  name: "Report.txt",
  media_type: "text/plain",
  size: 5,
  source_agent_id: "expert",
  source_thread_id: "child",
  source_kind: "device",
  source_device_id: "gpu",
  parse_state: "ready",
  publication_state: "published",
  content_url: "https://untrusted.invalid/private/path",
  download_url: "https://untrusted.invalid/private/path",
  created_at: 1792285260,
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal(
    "URL",
    class extends URL {
      static createObjectURL = vi.fn(() => "blob:verified");
      static revokeObjectURL = vi.fn();
    },
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("previews and downloads verified bytes through authenticated scoped routes, releases preview URLs", async () => {
  vi.mocked(request).mockResolvedValue(resource);
  vi.mocked(requestBlob).mockResolvedValue(
    new NativeBlob(["hello"]) as unknown as Blob,
  );
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  const view = render(
    <ResourcePanelContent
      agentId="parent"
      threadId="root"
      resourceId="opaque/report"
    />,
  );
  expect(screen.getByRole("status")).toHaveTextContent("collaboration.loading");
  expect(await screen.findByText("hello")).toBeInTheDocument();
  expect(screen.getByText(/collaboration.verified/)).toBeInTheDocument();
  expect(request).toHaveBeenCalledWith(
    "/agents/parent/threads/root/resources/opaque%2Freport",
  );
  expect(requestBlob).toHaveBeenCalledWith(
    "/agents/parent/threads/root/resources/opaque%2Freport/content",
  );
  fireEvent.click(screen.getByRole("button", { name: "common.download" }));
  await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
  expect(requestBlob).toHaveBeenLastCalledWith(
    "/agents/parent/threads/root/resources/opaque%2Freport/content?download=true",
  );
  expect(click.mock.instances[0].download).toBe("Report.txt");
  view.unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:verified");
  click.mockRestore();
});

it("refuses a changed version before preview or download can report success", async () => {
  vi.mocked(request).mockResolvedValue(resource);
  vi.mocked(requestBlob).mockResolvedValue(
    new NativeBlob(["wrong"]) as unknown as Blob,
  );
  render(
    <ResourcePanelContent
      agentId="parent"
      threadId="root"
      resourceId="opaque/report"
    />,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "collaboration.resourceError",
  );
  expect(screen.queryByText("wrong")).not.toBeInTheDocument();
  expect(screen.queryByText(/collaboration.verified/)).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "common.download" }),
  ).toBeDisabled();
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});

it("refresh clears an already shown artifact when access is revoked", async () => {
  vi.mocked(request)
    .mockResolvedValueOnce(resource)
    .mockRejectedValueOnce(new Error("secret path"));
  vi.mocked(requestBlob).mockResolvedValue(
    new NativeBlob(["hello"]) as unknown as Blob,
  );
  render(
    <ResourcePanelContent
      agentId="parent"
      threadId="root"
      resourceId="opaque/report"
    />,
  );
  await screen.findByText("hello");
  fireEvent.click(screen.getByRole("button", { name: "common.refresh" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "collaboration.resourceError",
  );
  expect(screen.queryByText("hello")).not.toBeInTheDocument();
  expect(screen.queryByText("secret path")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "common.download" }),
  ).toBeDisabled();
});
