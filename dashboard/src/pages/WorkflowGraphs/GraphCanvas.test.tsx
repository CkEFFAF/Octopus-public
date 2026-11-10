import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GraphCanvas } from "./GraphCanvas";
import { example } from "./definitions";

const tr = (key: string) => key;
describe("workflow canvas authoring", () => {
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
