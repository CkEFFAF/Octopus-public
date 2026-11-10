import { describe, expect, it } from "vitest";
import { example, kinds, makeNode } from "./definitions";

describe("shared workflow definitions", () => {
  it.each(["blank", "daily", "iteration", "event"] as const)(
    "builds the %s example with valid references",
    (kind) => {
      const graph = example(kind, "expert"),
        ids = new Set(graph.nodes.map((n) => n.id));
      expect(graph.nodes.filter((n) => n.kind === "entry")).toHaveLength(1);
      expect(graph.nodes.filter((n) => n.kind === "end")).toHaveLength(1);
      for (const edge of graph.edges) {
        expect(ids.has(edge.source)).toBe(true);
        expect(ids.has(edge.target)).toBe(true);
      }
    },
  );
  it("allocates independent editable nodes without shared context objects", () => {
    const a = makeNode("agent", "A", 0),
      b = makeNode("agent", "B", 1);
    a.context!.before.session = "new";
    expect(b.context!.before.session).toBe("current");
    expect(a.id).not.toBe(b.id);
    expect(kinds).toHaveLength(10);
  });
});
