import {
  act,
  fireEvent,
  render,
  screen,
  within,
  waitFor,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { request } from "../../../api/request";
import FileChangesReview from "./FileChangesReview";
import { changedFileKey } from "../utils/changedFiles";
import type { TurnFileChange } from "../utils/turnFileChanges";
vi.mock("../../../api/request", () => ({
  request: vi.fn(),
  requestBlob: vi.fn(),
}));
const change = (path: string): TurnFileChange => ({
  key: changedFileKey(path, "gpu"),
  path,
  agentId: "gpu",
  confirmed: true,
  edits: [
    { id: path, kind: "replace", before: "before", after: "recorded change" },
  ],
});
describe("file changes with live contents", () => {
  it("shows all files, marks the selected turn, and reads the current full content independently", async () => {
    vi.mocked(request).mockResolvedValue({
      content: "current complete content including later changes",
    });
    const a = change("/repo/a.py"),
      b = change("b.py");
    render(<FileChangesReview files={[a, b]} current={[a]} />);
    expect(
      within(screen.getByRole("navigation")).getByText("a.py"),
    ).toBeVisible();
    expect(screen.getByText("b.py")).toBeVisible();
    expect(
      screen.getAllByLabelText("chat.fileReview.currentTurn"),
    ).toHaveLength(1);
    expect(screen.queryByText(a.path)).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "chat.fileReview.details" }),
    );
    await waitFor(() => expect(screen.getByText(a.path)).toBeVisible());
    expect(screen.getByText("recorded change")).toBeVisible();
    expect(
      await screen.findByText(
        "current complete content including later changes",
      ),
    ).toBeVisible();
    expect(request).toHaveBeenCalledWith(
      expect.stringContaining("file%3A%2F%2F%2Frepo%2Fa.py"),
      expect.anything(),
    );
  });
  it("switches the narrow review pane while retaining the selected file", async () => {
    vi.mocked(request).mockResolvedValue({ content: "live content" });
    const a = change("a.py");
    render(<FileChangesReview files={[a]} current={[a]} />);
    await screen.findByText("live content");
    fireEvent.click(
      screen.getByRole("tab", { name: "chat.fileReview.fullContent" }),
    );
    expect(
      screen.getByRole("tab", { name: "chat.fileReview.fullContent" }),
    ).toHaveAttribute("aria-selected", "true");
    expect(
      screen.getByRole("region", { name: "chat.fileReview.fullContent" }),
    ).toHaveAttribute("data-active", "true");
    expect(
      screen.getByRole("region", { name: "chat.turnChanges.diff" }),
    ).toHaveAttribute("data-active", "false");
  });
  it("does not mix a late file response into the next selected file", async () => {
    let resolveFirst!: (value: unknown) => void;
    vi.mocked(request)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirst = resolve;
          }),
      )
      .mockResolvedValueOnce({ content: "B current" });
    const a = change("a.py"),
      b = change("b.py");
    render(<FileChangesReview files={[a, b]} current={[a]} />);
    fireEvent.click(screen.getByText("b.py"));
    expect(await screen.findByText("B current")).toBeVisible();
    await act(async () => resolveFirst({ content: "A stale" }));
    expect(screen.queryByText("A stale")).toBeNull();
  });
});
