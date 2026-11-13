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
import { providerApi } from "../../api/modules/provider";
import { Inspector, JsonField } from "./Inspector";

vi.mock("../../api/modules/workflowGraphs", () => ({
  workflowGraphsApi: { normalize: vi.fn() },
}));
vi.mock("../../api/modules/provider", () => ({
  providerApi: { listResolvedModels: vi.fn(async () => []) },
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

describe("workflow node forms", () => {
  it("discards an old expert's model response after switching experts", async () => {
    const response =
      deferred<Awaited<ReturnType<typeof providerApi.listResolvedModels>>>();
    vi.mocked(providerApi.listResolvedModels)
      .mockReturnValueOnce(response.promise)
      .mockResolvedValueOnce([
        {
          provider_id: 2,
          provider_name: "new",
          provider_kind: "openai",
          model: "new",
          name: "New model",
        },
      ]);
    const props = {
      graph,
      node: graph.nodes[0],
      agents: [],
      onChange: vi.fn(),
      tr,
    };
    const view = render(<Inspector {...props} />);
    view.rerender(
      <Inspector {...props} node={{ ...graph.nodes[0], agent_id: "other" }} />,
    );
    await act(async () =>
      response.resolve([
        {
          provider_id: 1,
          provider_name: "old",
          provider_kind: "openai",
          model: "old",
          name: "Old model",
        },
      ]),
    );
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "model" }));
    expect(await screen.findByText("new / New model")).toBeInTheDocument();
    expect(screen.queryByText("old / Old model")).not.toBeInTheDocument();
  });

  it("loads model choices for the effective expert and saves a configured reference", async () => {
    vi.mocked(providerApi.listResolvedModels).mockResolvedValueOnce([
      {
        provider_id: 1,
        provider_name: "configured",
        provider_kind: "openai",
        model: "deepseek",
        name: "DeepSeek",
      },
    ]);
    const changed = vi.fn();
    render(
      <Inspector
        graph={graph}
        node={graph.nodes[0]}
        agents={[]}
        onChange={changed}
        tr={tr}
      />,
    );
    await waitFor(() =>
      expect(providerApi.listResolvedModels).toHaveBeenCalledWith("expert"),
    );
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "model" }));
    fireEvent.click(await screen.findByText("configured / DeepSeek"));
    expect(changed).toHaveBeenCalledWith({
      ...graph,
      nodes: [{ ...graph.nodes[0], model: "configured/deepseek" }],
    });
    expect(
      screen.queryByRole("textbox", { name: "nodeDefinition" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: "history" }),
    ).not.toBeInTheDocument();
  });

  it("uses a typed condition value and hides the unused comparison for truthy", () => {
    const node = {
      ...graph.nodes[0],
      kind: "condition" as const,
      operator: "truthy",
      left: { path: "$.vars.improved" },
      right: { value: true },
    };
    render(
      <Inspector
        graph={{ ...graph, nodes: [node] }}
        node={node}
        agents={[]}
        onChange={vi.fn()}
        tr={tr}
      />,
    );
    expect(screen.getByRole("combobox", { name: "left" })).toHaveValue(
      "$.vars.improved",
    );
    expect(
      screen.queryByRole("combobox", { name: "right" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: "left" }),
    ).not.toBeInTheDocument();
  });
});
