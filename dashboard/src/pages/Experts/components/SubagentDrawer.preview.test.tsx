import { fireEvent, render, screen } from "@testing-library/react";
import { Form } from "antd";
import { expect, it, vi } from "vitest";
import { SubagentDrawer } from "./SubagentDrawer";

vi.mock("../../../components/ExpertColorPicker", () => ({
  default: () => null,
}));
vi.mock("../../../components/EmojiPicker", () => ({ default: () => null }));
const editing = {
  slug: "reviewer",
  path: "/reviewer.md",
  content:
    "---\nname: Reviewer\ndescription: Code review\n---\n\n# 审查要求\n\n- 核对结果\n",
};

it("previews subagent Markdown body without frontmatter and keeps source edits", async () => {
  function Example() {
    const [form] = Form.useForm();
    return (
      <SubagentDrawer
        open
        editing={editing}
        form={form}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />
    );
  }
  render(<Example />);
  await vi.dynamicImportSettled();
  expect(
    await screen.findByRole("heading", { name: "审查要求" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByText(/description: Code review/),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "workspace0034.source" }));
  fireEvent.change(screen.getByPlaceholderText("subagents.bodyPlaceholder"), {
    target: { value: "# 更新要求" },
  });
  fireEvent.click(screen.getByRole("button", { name: "common.preview" }));
  expect(
    await screen.findByRole("heading", { name: "更新要求" }),
  ).toBeInTheDocument();
});
