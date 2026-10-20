import { act, render, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import DocumentPreviewCore from "./DocumentPreviewCore";

vi.mock("docx-preview", () => ({
  renderAsync: async (_: ArrayBuffer, host: HTMLElement) => {
    host.innerHTML =
      '<div class="docx-doc-wrapper"><section class="docx-doc">First page</section><section class="docx-doc">Second page</section></div>';
  },
}));
vi.mock("react-pdf", () => ({
  Document: () => <div />,
  Page: () => <div />,
  pdfjs: { GlobalWorkerOptions: { workerSrc: "" } },
}));
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("preserves Word page identity and locates the same page region after pane resize", async () => {
  let width = 400;
  const callbacks: ResizeObserverCallback[] = [];
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: ResizeObserverCallback) {
        callbacks.push(callback);
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(
    () => width,
  );
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(800);
  Element.prototype.scrollIntoView = vi.fn();
  const fetchBlob = vi.fn(
    async () => ({ arrayBuffer: async () => new ArrayBuffer(1) }) as Blob,
  );
  const { container, rerender } = render(
    <DocumentPreviewCore
      kind="word"
      filename="report.docx"
      fetchBlob={fetchBlob}
    />,
  );
  await waitFor(() =>
    expect(container.querySelector('[data-document-page="2"]')).toBeTruthy(),
  );
  const second = container.querySelector<HTMLElement>(
    '[data-document-page="2"]',
  )!;
  width = 640;
  act(() =>
    callbacks.forEach((callback) => callback([], {} as ResizeObserver)),
  );
  expect(container.querySelector('[data-document-page="2"]')).toBe(second);
  rerender(
    <DocumentPreviewCore
      kind="word"
      filename="report.docx"
      fetchBlob={fetchBlob}
      location={{ kind: "page", page: 2, rect: [0.1, 0.2, 0.3, 0.4] }}
    />,
  );
  await waitFor(() =>
    expect(
      second.querySelector('[data-annotation-region="true"]'),
    ).toBeTruthy(),
  );
  expect(
    container.querySelector(
      '[data-document-page="1"] [data-annotation-region]',
    ),
  ).toBeNull();
});
