import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NodeDetail } from "./TaskActivity";
import type { ActivityNode } from "../../../api/modules/activity";
const mocks = vi.hoisted(() => ({ detail: vi.fn() }));
vi.mock("../../../api/modules/collaboration", () => ({
  collaborationApi: { detail: mocks.detail },
}));
vi.mock("../../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "UTC",
}));
vi.mock("../../../components/Markdown", () => ({
  default: ({ content }: { content: string }) => <p>{content}</p>,
}));
describe("selected node async boundary", () => {
  it("does not label unread logs from a cancelled job as completed output", () => {
    render(
      <NodeDetail
        node={{
          id: "job:context:614cd0fda8a6afc286d5379cbd92ea96",
          type: "job",
          name: "614cd0fda8a6afc286d5379cbd92ea96",
          status: "cancelled",
          updated_at: 1,
          dependencies_known: false,
          details: { job_id: "614cd0fda8a6afc286d5379cbd92ea96" },
        }}
        agentId="a"
        threadId="t"
      />,
    );
    expect(
      screen.getByRole("heading", { name: "workspace0034.nodeType.job" }),
    ).toBeTruthy();
    expect(screen.getByText("#bd92ea96")).toBeTruthy();
    expect(screen.getByText("workspace0034.status.cancelled")).toBeTruthy();
    expect(screen.getByText("workspace0034.logsNotLoaded")).toBeTruthy();
    expect(screen.queryByText("workspace0034.noPublicOutput")).toBeNull();
  });
  it("ignores an old detail response after selecting another node", async () => {
    let first: (value: unknown) => void = () => {};
    mocks.detail
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            first = resolve;
          }),
      )
      .mockResolvedValueOnce({
        messages: [
          {
            seq: 2,
            role: "assistant",
            content: [{ type: "text", text: "New public reply" }],
            created_at: 1,
          },
        ],
        has_more: false,
        next_before: null,
      });
    const node = (id: string): ActivityNode => ({
      id,
      type: "delegation",
      name: id,
      status: "running",
      updated_at: 1,
      dependencies_known: false,
    });
    const { rerender } = render(
      <NodeDetail node={node("old")} agentId="a" threadId="t" />,
    );
    rerender(<NodeDetail node={node("new")} agentId="a" threadId="t" stale />);
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByText("New public reply")).toBeTruthy();
    await act(async () => {
      first({
        messages: [
          { seq: 1, role: "assistant", content: "Old reply", created_at: 1 },
        ],
        has_more: false,
      });
    });
    expect(screen.queryByText("Old reply")).toBeNull();
    expect(screen.getByText("workspace0034.status.stale")).toBeTruthy();
  });
});
