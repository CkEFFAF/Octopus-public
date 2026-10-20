import { fireEvent, render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import * as XLSX from "xlsx";
import DocumentPreviewCore from "./DocumentPreviewCore";
vi.mock("react-pdf", () => ({
  Document: () => <div />,
  Page: () => <div />,
  pdfjs: { GlobalWorkerOptions: { workerSrc: "" } },
}));
describe("worksheet annotation coordinates", () => {
  it("preserves range origins, AA columns and switches sheets on locate", async () => {
    Element.prototype.scrollIntoView = vi.fn();
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(
      workbook,
      {
        C8: { t: "s", v: "Header" },
        C9: { t: "s", v: "Body" },
        AA8: { t: "s", v: "Far header" },
        AA9: { t: "s", v: "Far body" },
        "!ref": "C8:AA9",
      },
      "First",
    );
    XLSX.utils.book_append_sheet(
      workbook,
      {
        D5: { t: "s", v: "Second header" },
        D6: { t: "s", v: "Second body" },
        "!ref": "D5:D6",
      },
      "Second",
    );
    const buffer = XLSX.write(workbook, { type: "array", bookType: "xlsx" });
    const fetchBlob = vi.fn(
      async () => ({ arrayBuffer: async () => buffer }) as Blob,
    );
    const select = vi.fn();
    const { container, rerender } = render(
      <DocumentPreviewCore
        kind="excel"
        filename="sample.xlsx"
        fetchBlob={fetchBlob}
        onCellSelect={select}
      />,
    );
    await waitFor(() =>
      expect(container.querySelector('[data-cell="AA9"]')).toBeTruthy(),
    );
    fireEvent.click(container.querySelector('[data-cell="AA9"]')!);
    expect(select).toHaveBeenCalledWith("First", "AA9");
    expect(container.querySelector('[data-cell="C9"]')?.textContent).toBe(
      "Body",
    );
    rerender(
      <DocumentPreviewCore
        kind="excel"
        filename="sample.xlsx"
        fetchBlob={fetchBlob}
        onCellSelect={select}
        location={{ kind: "sheet", sheet: "Second", cells: "D6" }}
      />,
    );
    await waitFor(() =>
      expect(
        (container.querySelector('[data-cell="D6"]') as HTMLElement)?.style
          .outline,
      ).toContain("3px"),
    );
    expect(container.querySelector('[data-sheet-name="Second"]')).toBeTruthy();
  });
});
