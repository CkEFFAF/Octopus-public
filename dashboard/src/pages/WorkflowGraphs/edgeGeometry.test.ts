import { describe, expect, it } from "vitest";
import type { GraphEdge, GraphNode } from "../../api/modules/workflowGraphs";
import { routeEdges, type EdgeRoute, type Point } from "./edgeGeometry";

const node = (
  id: string,
  x: number,
  y: number,
  kind: GraphNode["kind"] = "script",
): GraphNode => ({ id, label: id, kind, position: { x, y } });
const edge = (
  id: string,
  source: string,
  target: string,
  port: GraphEdge["port"] = "next",
): GraphEdge => ({ id, source, target, port });

function segments(points: Point[]): [Point, Point][] {
  return points.slice(1).map((point, index) => [points[index], point]);
}

function avoidsCards(route: EdgeRoute, nodes: GraphNode[]) {
  for (const [start, end] of segments(route.points)) {
    expect(start.x === end.x || start.y === end.y).toBe(true);
    for (const card of nodes) {
      const { x, y } = card.position;
      const height =
        card.kind === "agent"
          ? 194
          : card.kind === "condition"
          ? 196
          : card.kind === "end"
          ? 112
          : 168;
      const crosses =
        start.y === end.y
          ? start.y > y &&
            start.y < y + height &&
            Math.min(start.x, end.x) < x + 272 &&
            Math.max(start.x, end.x) > x
          : start.x > x &&
            start.x < x + 272 &&
            Math.min(start.y, end.y) < y + height &&
            Math.max(start.y, end.y) > y;
      expect(
        crosses,
        `${card.id} intersects ${JSON.stringify([start, end])}`,
      ).toBe(false);
    }
  }
  expect(
    segments(route.points).some(
      ([a, b]) =>
        route.label.x >= Math.min(a.x, b.x) &&
        route.label.x <= Math.max(a.x, b.x) &&
        route.label.y >= Math.min(a.y, b.y) &&
        route.label.y <= Math.max(a.y, b.y),
    ),
  ).toBe(true);
}

describe("workflow edge geometry", () => {
  it("retains a visible cubic fallback when overlapping cards obscure a port", () => {
    const nodes = [
      node("source", 0, 0, "agent"),
      node("target", 140, 0, "agent"),
    ];
    const routed = routeEdges(nodes, [edge("overlap", "source", "target")]).get(
      "overlap",
    )!;
    expect(routed).toBeDefined();
    expect(routed.path).toContain("C");
    expect(routed.points[0]).toEqual({ x: 272, y: 152 });
    expect(routed.points.at(-1)).toEqual({ x: 140, y: 54 });
    expect(routed.label).toEqual({ x: 206, y: 103 });
  });

  it("routes around the full height of an intermediate agent card", () => {
    const nodes = [
      node("source", 0, 54),
      node("obstacle", 450, 0, "agent"),
      node("target", 1000, 126, "end"),
    ];
    const routed = routeEdges(nodes, [edge("forward", "source", "target")]).get(
      "forward",
    )!;
    expect(routed).toBeDefined();
    expect(routed.points[0]).toEqual({ x: 272, y: 180 });
    expect(routed.points.at(-1)).toEqual({ x: 1000, y: 180 });
    expect(routed.points.some((point) => point.y < 0 || point.y > 194)).toBe(
      true,
    );
    expect(routed.path).not.toContain("C");
    avoidsCards(routed, nodes);
  });

  it("takes a back edge around its endpoint cards and other intervening cards", () => {
    const nodes = [
      node("target", 0, 0),
      node("middle", 350, 0, "agent"),
      node("source", 700, 0, "agent"),
    ];
    const routed = routeEdges(nodes, [edge("back", "source", "target")]).get(
      "back",
    )!;
    expect(routed).toBeDefined();
    expect(routed.points[1].x).toBeGreaterThan(routed.points[0].x);
    expect(routed.points.at(-2)!.x).toBeLessThan(routed.points.at(-1)!.x);
    expect(routed.points.some((point) => point.y < 0 || point.y > 194)).toBe(
      true,
    );
    avoidsCards(routed, nodes);
  });

  it("takes a self loop outside the whole card and enters the left input", () => {
    const nodes = [node("self", 100, 100, "condition")];
    const routed = routeEdges(nodes, [
      edge("loop", "self", "self", "false"),
    ]).get("loop")!;
    expect(routed).toBeDefined();
    expect(routed.points[0]).toEqual({ x: 372, y: 254 });
    expect(routed.points.at(-1)).toEqual({ x: 100, y: 154 });
    expect(routed.points.some((point) => point.x > 372)).toBe(true);
    expect(routed.points.some((point) => point.x < 100)).toBe(true);
    expect(routed.points.some((point) => point.y < 100 || point.y > 296)).toBe(
      true,
    );
    avoidsCards(routed, nodes);
  });

  it("uses each actual condition output port and target input at y plus 54", () => {
    const nodes = [
      node("condition", 100, 50, "condition"),
      node("yes", 900, 0, "end"),
      node("no", 900, 300, "end"),
      node("error", 900, 600, "end"),
    ];
    const edges = [
      edge("true", "condition", "yes", "true"),
      edge("false", "condition", "no", "false"),
      edge("error", "condition", "error", "error"),
    ];
    const routed = routeEdges(nodes, edges);
    for (const [index, item] of edges.entries()) {
      const route = routed.get(item.id)!;
      expect(route.points[0]).toEqual({ x: 372, y: 176 + index * 28 });
      expect(route.points.at(-1)).toEqual({ x: 900, y: index * 300 + 54 });
      avoidsCards(route, nodes);
    }
  });

  it("keeps close neighboring cards connected without cutting through them", () => {
    const nodes = [
      node("source", 0, 0, "agent"),
      node("target", 288, 0, "agent"),
    ];
    const routed = routeEdges(nodes, [edge("close", "source", "target")]).get(
      "close",
    )!;
    expect(routed).toBeDefined();
    avoidsCards(routed, nodes);
  });

  it("keeps all 44 connections clear in a 32 node graph without mutating definitions", () => {
    const nodes = Array.from({ length: 32 }, (_, index) =>
      node(
        `n${index}`,
        (index % 8) * 440,
        Math.floor(index / 8) * 280,
        "agent",
      ),
    );
    const edges = [
      ...nodes
        .slice(1)
        .map((_, index) => edge(`next${index}`, `n${index}`, `n${index + 1}`)),
      ...nodes
        .slice(0, 13)
        .map((_, index) =>
          edge(`branch${index}`, `n${index + 8}`, `n${index}`, "error"),
        ),
    ];
    const original = JSON.stringify({ nodes, edges });
    const routed = routeEdges(nodes, edges);
    expect(routed.size).toBe(44);
    for (const route of routed.values()) avoidsCards(route, nodes);
    expect(JSON.stringify({ nodes, edges })).toBe(original);
  });
});
