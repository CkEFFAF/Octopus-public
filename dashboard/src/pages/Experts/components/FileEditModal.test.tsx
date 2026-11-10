import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import FileEditModal from "./FileEditModal";

vi.mock("@monaco-editor/react", () => ({
  default: ({
    value,
    onChange,
  }: {
    value: string;
    onChange: (value: string) => void;
  }) => (
    <textarea
      aria-label="Test source"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  ),
}));

it("previews expert Markdown, preserves edits through preview and only saves explicitly", async () => {
  const save = vi.fn();
  render(
    <FileEditModal
      open
      filePath="/SOUL.md"
      localValue="# 专家说明"
      onLocalSave={save}
      onClose={vi.fn()}
      onSaved={vi.fn()}
    />,
  );
  await vi.dynamicImportSettled();
  expect(
    await screen.findByRole("heading", { name: "专家说明" }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "workspace0034.source" }));
  fireEvent.change(
    await screen.findByRole("textbox", { name: "Test source" }),
    { target: { value: "# 更新说明" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "common.preview" }));
  expect(
    await screen.findByRole("heading", { name: "更新说明" }),
  ).toBeInTheDocument();
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "common.save" }));
  expect(save).toHaveBeenCalledWith("# 更新说明");
});
