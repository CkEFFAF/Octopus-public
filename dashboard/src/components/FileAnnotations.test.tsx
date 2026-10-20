import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FileAnnotations from "./FileAnnotations";
import type { CollaborationResource } from "../api/modules/collaboration";
import {
  annotationsApi,
  type FileAnnotation,
} from "../api/modules/annotations";
vi.mock("../api/modules/annotations", () => ({
  annotationsApi: {
    list: vi.fn(async () => ({ items: [], has_more: false, next_cursor: 0 })),
    requests: vi.fn(async () => ({ items: [] })),
    create: vi.fn(async () => ({})),
    update: vi.fn(async () => ({})),
  },
}));
beforeEach(() => vi.clearAllMocks());

const resource = {
  resource_id: "r",
  version: "a".repeat(64),
} as CollaborationResource;
const commonProps = {
  agentId: "a",
  threadId: "t",
  resource,
  onLocate: vi.fn(),
  onResult: vi.fn(),
};
describe("annotation selection compose", () => {
  it("whole-file comments do not reuse a previously located region", async () => {
    render(
      <FileAnnotations
        {...commonProps}
        anchor={{ kind: "image", rect: [0.1, 0.1, 0.2, 0.2] }}
        selectionRevision={0}
      />,
    );
    await act(async () => {
      await Promise.resolve();
    });
    fireEvent.click(
      screen.getByRole("button", { name: "workspace0034.commentWholeFile" }),
    );
    fireEvent.change(
      screen.getByPlaceholderText("workspace0034.commentPlaceholder"),
      { target: { value: "Review the whole file" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "workspace0034.saveComment" }),
    );
    await waitFor(() =>
      expect(annotationsApi.create).toHaveBeenCalledWith(
        "a",
        "t",
        "r",
        resource.version,
        { kind: "file" },
        "Review the whole file",
      ),
    );
  });

  it("keeps an unsaved comment attached to its selected text when locating elsewhere", async () => {
    const original = {
      kind: "text" as const,
      line: 1,
      quote: "Original selected text",
    };
    const view = render(
      <FileAnnotations
        {...commonProps}
        anchor={original}
        selectionRevision={1}
      />,
    );
    await act(async () => {
      await Promise.resolve();
    });
    fireEvent.change(
      screen.getByPlaceholderText("workspace0034.commentPlaceholder"),
      { target: { value: "Keep this draft attached" } },
    );
    view.rerender(
      <FileAnnotations
        {...commonProps}
        anchor={{ kind: "image", rect: [0.2, 0.3, 0.2, 0.1] }}
        selectionRevision={1}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "workspace0034.saveComment" }),
    );
    await waitFor(() =>
      expect(annotationsApi.create).toHaveBeenCalledWith(
        "a",
        "t",
        "r",
        resource.version,
        original,
        "Keep this draft attached",
      ),
    );
  });

  it("opens a reply on demand and sends it with the current comment revision", async () => {
    const item: FileAnnotation = {
      annotation_id: "c",
      resource_id: "r",
      version: resource.version,
      anchor: { kind: "file" },
      body: "Existing comment",
      status: "open",
      revision: 4,
      cursor: 1,
      replies: [],
    };
    vi.mocked(annotationsApi.list).mockResolvedValueOnce({
      items: [item],
      has_more: false,
      next_cursor: 1,
    });
    render(
      <FileAnnotations
        {...commonProps}
        anchor={{ kind: "file" }}
        selectionRevision={0}
      />,
    );
    await screen.findByText(item.body);
    expect(screen.queryByPlaceholderText("workspace0034.reply")).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "workspace0034.reply" }),
    );
    const input = screen.getByPlaceholderText("workspace0034.reply");
    fireEvent.change(input, { target: { value: "  Checked the peak  " } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter", charCode: 13 });
    await waitFor(() =>
      expect(annotationsApi.update).toHaveBeenCalledWith(
        "a",
        "t",
        "r",
        "c",
        4,
        { reply: "Checked the peak" },
      ),
    );
    await waitFor(() =>
      expect(screen.queryByPlaceholderText("workspace0034.reply")).toBeNull(),
    );
  });
  it("locates saved comments without starting a new draft, then composes a new selection", async () => {
    const item: FileAnnotation = {
      annotation_id: "comment-1",
      resource_id: "r",
      version: "a".repeat(64),
      anchor: { kind: "image", rect: [0.1, 0.2, 0.3, 0.4] },
      body: "Inspect this peak",
      status: "open",
      revision: 1,
      cursor: 1,
      replies: [],
    };
    vi.mocked(annotationsApi.list).mockResolvedValueOnce({
      items: [item],
      has_more: false,
      next_cursor: 1,
    });
    const props = {
      agentId: "a",
      threadId: "t",
      resource: {
        resource_id: "r",
        version: item.version,
      } as CollaborationResource,
      onLocate: vi.fn(),
      onResult: vi.fn(),
      selectionRevision: 0,
    };
    const view = render(
      <FileAnnotations {...props} anchor={{ kind: "file" }} />,
    );
    await screen.findByText(item.body);
    fireEvent.click(
      screen.getByRole("button", { name: /workspace0034.anchor.image/ }),
    );
    expect(props.onLocate).toHaveBeenCalledWith(item.anchor);
    view.rerender(<FileAnnotations {...props} anchor={item.anchor} />);
    expect(
      screen.queryByPlaceholderText("workspace0034.commentPlaceholder"),
    ).toBeNull();
    view.rerender(
      <FileAnnotations
        {...props}
        anchor={{ kind: "image", rect: [0.2, 0.3, 0.1, 0.1] }}
        selectionRevision={1}
      />,
    );
    expect(
      screen.getByPlaceholderText("workspace0034.commentPlaceholder"),
    ).toBeInTheDocument();
  });
  it("keeps the compose quiet until selecting a location or whole-file action", async () => {
    const props = {
      agentId: "a",
      threadId: "t",
      resource: {
        resource_id: "r",
        version: "a".repeat(64),
      } as CollaborationResource,
      onLocate: vi.fn(),
      onResult: vi.fn(),
      onClose: vi.fn(),
      selectionRevision: 0,
    };
    const { rerender } = render(
      <FileAnnotations {...props} anchor={{ kind: "file" }} />,
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(
      screen.queryByPlaceholderText("workspace0034.commentPlaceholder"),
    ).toBeNull();
    rerender(
      <FileAnnotations
        {...props}
        selectionRevision={1}
        anchor={{
          kind: "text",
          line: 1,
          column: 1,
          end_line: 1,
          end_column: 3,
          quote: "Hi",
        }}
      />,
    );
    expect(
      screen.getByPlaceholderText("workspace0034.commentPlaceholder"),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "common.close" }));
    expect(props.onClose).toHaveBeenCalledOnce();
  });
});
