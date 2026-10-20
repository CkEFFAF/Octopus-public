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
import type { FileAnchor } from "../../../api/modules/annotations";

vi.mock("../../../api/request", () => ({
  request: vi.fn(),
  requestBlob: vi.fn(),
}));
vi.mock("../../../components/DocumentPreviewCore", () => ({
  default: () => (
    <div data-document-page="2">
      <p>Document renderer</p>
    </div>
  ),
}));
vi.mock("../../../components/FileAnnotations", () => ({
  default: ({
    onClose,
    anchor,
    onResult,
  }: {
    onClose: () => void;
    anchor: FileAnchor;
    onResult: (id: string) => void;
  }) => (
    <aside aria-label="Test annotations">
      <output>{JSON.stringify(anchor)}</output>
      <button onClick={onClose}>Close annotations</button>
      <button onClick={() => onResult("revised")}>Open result</button>
    </aside>
  ),
}));
vi.mock("../../Agent/Workspace/components/CodeEditor", () => ({
  default: ({ value }: { value: string }) => <pre>{value}</pre>,
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

it("keeps the actual document page when text selection also fires after a region drag", async () => {
  vi.mocked(request).mockResolvedValue({
    ...resource,
    name: "report.docx",
    media_type:
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  });
  vi.mocked(requestBlob).mockResolvedValue(
    new NativeBlob(["hello"]) as unknown as Blob,
  );
  vi.stubGlobal("PointerEvent", MouseEvent);
  const view = render(
    <ResourcePanelContent agentId="a" threadId="t" resourceId="r" />,
  );
  const paragraph = await screen.findByText("Document renderer");
  const page = paragraph.parentElement!;
  vi.spyOn(page, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: 0,
    left: 0,
    top: 0,
    right: 100,
    bottom: 100,
    width: 100,
    height: 100,
    toJSON: () => ({}),
  });
  vi.spyOn(window, "getSelection").mockReturnValue({
    anchorNode: paragraph.firstChild,
    toString: () => "Document",
  } as unknown as Selection);
  fireEvent.pointerDown(page, { clientX: 10, clientY: 20 });
  fireEvent.pointerUp(page, { clientX: 40, clientY: 60 });
  fireEvent.mouseUp(page);
  await waitFor(() =>
    expect(view.container.querySelector("output")?.textContent).toContain(
      '"quote":"Document"',
    ),
  );
  const anchor = JSON.parse(
    view.container.querySelector("output")!.textContent!,
  );
  expect(anchor.kind).toBe("page");
  expect(anchor.page).toBe(2);
  expect(anchor.rect).toEqual([
    0.1, 0.2, 0.30000000000000004, 0.39999999999999997,
  ]);
  vi.restoreAllMocks();
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

it("keeps the preview visible when annotations are opened and closed", async () => {
  vi.mocked(request).mockResolvedValue(resource);
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
  expect(screen.queryByRole("complementary")).toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "workspace0034.annotations" }),
  );
  expect(screen.getByRole("complementary")).toBeInTheDocument();
  expect(screen.getByText("hello")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Close annotations" }));
  expect(screen.queryByRole("complementary")).toBeNull();
  expect(screen.getByText("hello")).toBeInTheDocument();
});

it("zooms verified images and retains normalized region anchors when fitting again", async () => {
  vi.mocked(request).mockResolvedValue({
    ...resource,
    name: "chart.png",
    media_type: "image/png",
  });
  vi.mocked(requestBlob).mockResolvedValue(
    new NativeBlob(["hello"]) as unknown as Blob,
  );
  vi.stubGlobal("PointerEvent", MouseEvent);
  const view = render(
    <ResourcePanelContent agentId="a" threadId="t" resourceId="image" />,
  );
  const image = await screen.findByRole("img", { name: "chart.png" });
  Object.defineProperty(image, "naturalWidth", { value: 1000 });
  vi.spyOn(image, "clientWidth", "get").mockImplementation(
    () => parseFloat(image.parentElement!.style.width) || 500,
  );
  fireEvent.load(image);
  expect(await screen.findByText("50%")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "workspace.pdfZoomIn" }));
  expect(image.parentElement).toHaveStyle({ width: "625px" });
  const region = image.parentElement!;
  region.setPointerCapture = vi.fn();
  vi.spyOn(region, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: 0,
    left: 0,
    top: 0,
    right: 625,
    bottom: 500,
    width: 625,
    height: 500,
    toJSON: () => ({}),
  });
  fireEvent.pointerDown(region, { clientX: 125, clientY: 100 });
  fireEvent.pointerUp(region, { clientX: 375, clientY: 300 });
  const anchor = JSON.parse(
    view.container.querySelector("output")!.textContent!,
  );
  expect(anchor.kind).toBe("image");
  anchor.rect.forEach((value: number, i: number) =>
    expect(value).toBeCloseTo([0.2, 0.2, 0.4, 0.4][i]),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "workspace.pdfFitWidth" }),
  );
  expect(region.style.width).toBe("");
  expect(
    JSON.parse(view.container.querySelector("output")!.textContent!),
  ).toEqual(anchor);
  vi.restoreAllMocks();
});

it("clears the old version selection when opening a modification result", async () => {
  vi.mocked(request).mockImplementation(async (path) => ({
    ...resource,
    name: path.endsWith("/revised") ? "Result.txt" : resource.name,
  }));
  vi.mocked(requestBlob).mockResolvedValue(
    new NativeBlob(["hello"]) as unknown as Blob,
  );
  render(
    <ResourcePanelContent agentId="a" threadId="t" resourceId="original" />,
  );
  const text = await screen.findByText("hello");
  vi.spyOn(window, "getSelection").mockReturnValue({
    anchorNode: text.firstChild,
    toString: () => "old version quote",
  } as unknown as Selection);
  fireEvent.mouseUp(text);
  expect(screen.getByRole("status")).toHaveTextContent("old version quote");
  fireEvent.click(screen.getByRole("button", { name: "Open result" }));
  await screen.findByText("Result.txt");
  expect(screen.queryByRole("complementary")).toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "workspace0034.annotations" }),
  );
  expect(screen.getByRole("status")).toHaveTextContent('{"kind":"file"}');
});
