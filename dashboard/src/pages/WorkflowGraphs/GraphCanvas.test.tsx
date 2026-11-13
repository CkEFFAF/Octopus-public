import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GraphCanvas } from "./GraphCanvas";
import { example } from "./definitions";
import * as geometry from "./edgeGeometry";

const tr = (key: string) => key;
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
describe("workflow canvas authoring", () => {
  it("keeps an existing edge visible and keyboard selectable when cards overlap", () => {
    const graph = example("blank", "expert"),
      selected = vi.fn();
    graph.nodes[1].position.x = 140;
    render(
      <GraphCanvas
        graph={graph}
        selected=""
        onSelect={selected}
        onChange={vi.fn()}
        activations={[]}
        tr={tr}
        readOnly
      />,
    );
    const connection = screen.getByRole("button", {
      name: "Start next Finish",
    });
    expect(connection.querySelector(".wg-edge")?.getAttribute("d")).toContain(
      "C",
    );
    fireEvent.keyDown(connection, { key: " " });
    expect(selected).toHaveBeenCalledWith(graph.edges[0].id);
  });

  it("keeps routed edges selectable in read-only runs and memoizes selection changes", () => {
    const graph = example("blank", "expert"),
      selected = vi.fn(),
      changed = vi.fn();
    const routes = geometry.routeEdges(graph.nodes, graph.edges);
    const routed = vi.spyOn(geometry, "routeEdges");
    const props = {
      graph,
      selected: "",
      onSelect: selected,
      onChange: changed,
      activations: [],
      tr,
      readOnly: true,
    };
    const view = render(<GraphCanvas {...props} />);
    const connection = screen.getByRole("button", {
      name: "Start next Finish",
    });
    const expected = routes.get(graph.edges[0].id)!;
    expect(connection.querySelector(".wg-edge")).toHaveAttribute(
      "d",
      expected.path,
    );
    expect(connection.querySelector("text")).toHaveAttribute(
      "x",
      String(expected.label.x),
    );
    expect(connection.querySelector("text")).toHaveAttribute(
      "y",
      String(expected.label.y),
    );
    fireEvent.keyDown(connection, { key: "Enter" });
    expect(selected).toHaveBeenCalledWith(graph.edges[0].id);
    expect(changed).not.toHaveBeenCalled();
    view.rerender(<GraphCanvas {...props} selected={graph.edges[0].id} />);
    expect(routed).toHaveBeenCalledTimes(1);
    expect(connection).toHaveClass("selected");
  });

  it("connects named ports with keyboard accessible buttons", () => {
    const graph = example("blank", "expert");
    graph.edges = [];
    const changed = vi.fn();
    render(
      <GraphCanvas
        graph={graph}
        selected=""
        onSelect={vi.fn()}
        onChange={changed}
        activations={[]}
        tr={tr}
      />,
    );
    fireEvent.click(
      within(screen.getByRole("region", { name: "Start" })).getByRole(
        "button",
        { name: "port.next" },
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "connectTo Finish" }));
    expect(changed.mock.calls[0][0].edges).toEqual([
      expect.objectContaining({
        source: "start",
        target: "finish",
        port: "next",
      }),
    ]);
  });

  it("moves a focused node with arrow keys", () => {
    const graph = example("blank", "expert"),
      changed = vi.fn();
    render(
      <GraphCanvas
        graph={graph}
        selected="start"
        onSelect={vi.fn()}
        onChange={changed}
        activations={[]}
        tr={tr}
      />,
    );
    fireEvent.keyDown(
      within(screen.getByRole("region", { name: "Start" })).getByRole(
        "button",
        { name: /kind.entry/ },
      ),
      { key: "ArrowRight" },
    );
    expect(changed.mock.calls[0][0].nodes[0].position.x).toBe(20);
    expect(graph.nodes[0].position.x).toBe(0);
  });

  it("keeps pinned run nodes read only while allowing selection", () => {
    const graph = example("blank", "expert"),
      changed = vi.fn(),
      selected = vi.fn();
    render(
      <GraphCanvas
        graph={graph}
        selected=""
        onSelect={selected}
        onChange={changed}
        activations={[]}
        tr={tr}
        readOnly
      />,
    );
    const node = within(
      screen.getByRole("region", { name: "Start" }),
    ).getByRole("button", { name: /kind.entry/ });
    fireEvent.keyDown(node, { key: "ArrowRight" });
    fireEvent.pointerDown(node, { clientX: 20, clientY: 20 });
    fireEvent.pointerMove(screen.getByLabelText("canvas"), {
      clientX: 40,
      clientY: 40,
    });
    fireEvent.pointerUp(screen.getByLabelText("canvas"));
    expect(changed).not.toHaveBeenCalled();
    expect(selected).toHaveBeenCalledWith("start");
    expect(
      screen.queryByRole("button", { name: "connectTo Finish" }),
    ).not.toBeInTheDocument();
  });
});
