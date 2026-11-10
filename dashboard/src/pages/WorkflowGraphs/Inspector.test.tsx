import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { GraphDefinition } from "../../api/modules/workflowGraphs";
import { workflowGraphsApi } from "../../api/modules/workflowGraphs";
import { Inspector, JsonField } from "./Inspector";

vi.mock("../../api/modules/workflowGraphs", () => ({
  workflowGraphsApi: { normalize: vi.fn() },
}));
afterEach(() => {
  cleanup();
  vi.mocked(workflowGraphsApi.normalize).mockReset();
});
const graph: GraphDefinition = {
  name: "Original",
  agent_id: "expert",
  edges: [],
  nodes: [
    { id: "agent", kind: "agent", label: "Analyze", position: { x: 0, y: 0 } },
  ],
};
const tr = (key: string) => key;
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
function editNode() {
  fireEvent.click(screen.getByText("advanced"));
  const input = screen.getByRole("textbox", { name: "nodeDefinition" });
  fireEvent.change(input, {
    target: { value: JSON.stringify({ ...graph.nodes[0], prompt: "Updated" }) },
  });
  fireEvent.blur(input);
}
describe("workflow JSON validation", () => {
  it("installs canonical defaults only after successful normalization", async () => {
    const canonical = {
      ...graph,
      nodes: [
        {
          ...graph.nodes[0],
          context: { before: { session: "current" as const }, after: {} },
        },
      ],
    };
    vi.mocked(workflowGraphsApi.normalize).mockResolvedValue({
      definition: canonical,
      issues: [],
    });
    const changed = vi.fn();
    render(
      <Inspector
        graph={graph}
        node={graph.nodes[0]}
        onChange={changed}
        agents={[]}
        tr={tr}
      />,
    );
    editNode();
    await waitFor(() => expect(changed).toHaveBeenCalledWith(canonical));
  });

  it("discards normalization after switching graphs or editing another field", async () => {
    const response =
      deferred<Awaited<ReturnType<typeof workflowGraphsApi.normalize>>>();
    vi.mocked(workflowGraphsApi.normalize).mockReturnValue(response.promise);
    const changed = vi.fn();
    const view = render(
      <Inspector
        graph={graph}
        node={graph.nodes[0]}
        onChange={changed}
        agents={[]}
        tr={tr}
      />,
    );
    editNode();
    const newer = { ...graph, name: "New draft" };
    view.rerender(
      <Inspector
        graph={newer}
        node={newer.nodes[0]}
        onChange={changed}
        agents={[]}
        tr={tr}
      />,
    );
    await act(async () => response.resolve({ definition: graph, issues: [] }));
    expect(changed).not.toHaveBeenCalled();
  });

  it("discards responses after closing the inspector", async () => {
    const response =
      deferred<Awaited<ReturnType<typeof workflowGraphsApi.normalize>>>();
    vi.mocked(workflowGraphsApi.normalize).mockReturnValue(response.promise);
    const changed = vi.fn();
    const view = render(
      <Inspector
        graph={graph}
        node={graph.nodes[0]}
        onChange={changed}
        agents={[]}
        tr={tr}
      />,
    );
    editNode();
    view.unmount();
    await act(async () => response.resolve({ definition: graph, issues: [] }));
    expect(changed).not.toHaveBeenCalled();
  });

  it("keeps newer JSON text and ignores an older validation error", async () => {
    const response = deferred<unknown>();
    const changed = vi.fn();
    render(
      <JsonField
        label="JSON"
        value={{}}
        onChange={changed}
        normalize={() => response.promise}
      />,
    );
    const input = screen.getByRole("textbox", { name: "JSON" });
    fireEvent.change(input, { target: { value: '{"old":1}' } });
    fireEvent.blur(input);
    fireEvent.change(input, { target: { value: '{"new":2}' } });
    await act(async () => response.reject(new Error("Old validation")));
    expect(input).toHaveValue('{"new":2}');
    expect(screen.queryByText(/Old validation/)).not.toBeInTheDocument();
    expect(changed).not.toHaveBeenCalled();
  });
});
