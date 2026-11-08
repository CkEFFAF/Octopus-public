import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import FileViewer from "./FileViewer";
vi.mock("./DocumentPreview", () => ({ default: () => null }));

it("opens uppercase .markdown files as rendered documents instead of binaries", async () => {
  render(
    <FileViewer
      path="/notes.MARKDOWN"
      editMode={false}
      value={"# 工作记录\n\n- 已完成"}
      onChange={() => {}}
    />,
  );
  expect(
    await screen.findByRole("heading", { name: "工作记录" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("listitem")).toHaveTextContent("已完成");
});
