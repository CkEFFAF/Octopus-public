import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import TaskActivityGraph from "./TaskActivityGraph";
import type {
  ActivitySnapshot,
  ActivityNode,
} from "../../../api/modules/activity";
vi.mock("./TaskActivity", () => ({
  ActivityStatus: ({ node }: { node: ActivityNode }) => (
    <span>{node.status}</span>
  ),
}));
describe("actual executors inside explicit plan cards", () => {
  it("shows one explicit run by default and lets the user inspect earlier runs", () => {
    const snapshot = {
      nodes: [
        {
          id: "earlier",
          type: "plan",
          name: "Earlier plan",
          run_id: "one",
          updated_at: 1,
          status: "completed",
          dependencies_known: true,
        },
        {
          id: "latest",
          type: "plan",
          name: "Latest plan",
          run_id: "two",
          updated_at: 2,
          status: "running",
          dependencies_known: true,
        },
      ],
      edges: [],
      observed_at: 2,
      scope_truncated: false,
      next_before: null,
      counts: { subagents: 0, jobs: 0, parallel: 0, completed: 1 },
    } as ActivitySnapshot;
    const select = vi.fn();
    render(
      <TaskActivityGraph
        snapshot={snapshot}
        selected=""
        onSelect={select}
        stale={false}
      />,
    );
    expect(screen.getByText("Latest plan")).toBeTruthy();
    expect(screen.queryByText("Earlier plan")).toBeNull();
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "one" },
    });
    expect(screen.getByText("Earlier plan")).toBeTruthy();
    expect(screen.queryByText("Latest plan")).toBeNull();
    expect(select).toHaveBeenCalledWith("");
  });
  it("keeps linked executions separate from unlinked and makes every attempt reachable", () => {
    const node = (id: string, type: string): ActivityNode => ({
      id,
      type,
      name: id,
      status: "running",
      updated_at: 1,
      dependencies_known: type !== "tool",
    });
    const nodes = [
      node("plan", "plan"),
      node("worker1", "subagent"),
      node("worker2", "subagent"),
      node("job1", "job"),
      node("retry-job", "job"),
      node("unlinked", "tool"),
    ];
    const snapshot = {
      nodes,
      edges: nodes
        .slice(1, 5)
        .map((n) => ({ from: "plan", to: n.id, kind: "contains" })),
      observed_at: 1,
      scope_truncated: false,
      next_before: null,
      counts: { subagents: 2, jobs: 2, parallel: 1, completed: 0 },
    } as ActivitySnapshot;
    const select = vi.fn();
    render(
      <TaskActivityGraph
        snapshot={snapshot}
        selected=""
        onSelect={select}
        stale={false}
      />,
    );
    fireEvent.click(screen.getByText("worker1"));
    expect(select).toHaveBeenCalledWith("worker1");
    fireEvent.click(screen.getByText("workspace0034.taskActivityMore"));
    fireEvent.click(screen.getByText("worker2"));
    expect(select).toHaveBeenCalledWith("worker2");
    expect(screen.getByText("unlinked")).toBeTruthy();
    expect(screen.getAllByTitle("retry-job").length).toBeGreaterThan(0);
  });
});
