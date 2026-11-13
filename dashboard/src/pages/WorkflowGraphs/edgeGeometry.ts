import type { GraphEdge, GraphNode } from "../../api/modules/workflowGraphs";
import {
  NODE_WIDTH,
  PORT_HEIGHT,
  nodeHeaderHeight,
  nodePorts,
} from "./nodePresentation";

export interface Point {
  x: number;
  y: number;
}
export interface EdgeRoute {
  path: string;
  points: Point[];
  label: Point;
}
interface Rectangle {
  left: number;
  right: number;
  top: number;
  bottom: number;
}
interface Anchors {
  source: Point;
  target: Point;
  start: Point;
  end: Point;
}
interface Grid {
  xs: number[];
  ys: number[];
  columns: Map<number, number>;
  rows: Map<number, number>;
  horizontal: Uint8Array;
  vertical: Uint8Array;
  rectangles: Rectangle[];
}

const CLEARANCE = 12;
const PORT_STUB = 24;
const TURN_COST = 24;

function nodeRectangle(node: GraphNode, clearance: number): Rectangle {
  return {
    left: node.position.x - clearance,
    right: node.position.x + NODE_WIDTH + clearance,
    top: node.position.y - clearance,
    bottom:
      node.position.y +
      nodeHeaderHeight(node) +
      nodePorts(node).length * PORT_HEIGHT +
      clearance,
  };
}

function contains(rectangle: Rectangle, x: number, y: number) {
  return (
    x > rectangle.left &&
    x < rectangle.right &&
    y > rectangle.top &&
    y < rectangle.bottom
  );
}

function makeGrid(
  nodes: GraphNode[],
  anchors: Anchors[],
  clearance: number,
): Grid {
  const rectangles = nodes.map((node) => nodeRectangle(node, clearance));
  const xValues = rectangles.flatMap((rectangle) => [
    rectangle.left,
    rectangle.right,
  ]);
  const yValues = rectangles.flatMap((rectangle) => [
    rectangle.top,
    rectangle.bottom,
  ]);
  for (const { start, end } of anchors) {
    xValues.push(start.x, end.x);
    yValues.push(start.y, end.y);
  }
  xValues.push(
    Math.min(...xValues) - PORT_STUB,
    Math.max(...xValues) + PORT_STUB,
  );
  yValues.push(
    Math.min(...yValues) - PORT_STUB,
    Math.max(...yValues) + PORT_STUB,
  );
  const xs = [...new Set(xValues)].sort((a, b) => a - b);
  const ys = [...new Set(yValues)].sort((a, b) => a - b);
  const width = xs.length;
  const horizontal = new Uint8Array(width * ys.length);
  const vertical = new Uint8Array(width * ys.length);
  for (let y = 0; y < ys.length; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const cell = y * width + x;
      // Every obstacle boundary is a grid coordinate. Between adjacent grid
      // coordinates a midpoint test therefore covers the complete segment.
      if (x + 1 < width)
        horizontal[cell] = +!rectangles.some((rectangle) =>
          contains(rectangle, (xs[x] + xs[x + 1]) / 2, ys[y]),
        );
      if (y + 1 < ys.length)
        vertical[cell] = +!rectangles.some((rectangle) =>
          contains(rectangle, xs[x], (ys[y] + ys[y + 1]) / 2),
        );
    }
  }
  return {
    xs,
    ys,
    horizontal,
    vertical,
    rectangles,
    columns: new Map(xs.map((value, index) => [value, index])),
    rows: new Map(ys.map((value, index) => [value, index])),
  };
}

// A binary heap avoids scanning the whole frontier for every shortest-path step.
class Frontier {
  private items: { state: number; score: number }[] = [];
  push(state: number, score: number) {
    const item = { state, score };
    let index = this.items.length;
    this.items.push(item);
    while (index > 0) {
      const parent = (index - 1) >> 1;
      if (this.items[parent].score <= score) break;
      this.items[index] = this.items[parent];
      index = parent;
    }
    this.items[index] = item;
  }
  pop() {
    const first = this.items[0];
    const last = this.items.pop();
    if (this.items.length && last) {
      let index = 0;
      while (index * 2 + 1 < this.items.length) {
        let child = index * 2 + 1;
        if (
          child + 1 < this.items.length &&
          this.items[child + 1].score < this.items[child].score
        )
          child += 1;
        if (this.items[child].score >= last.score) break;
        this.items[index] = this.items[child];
        index = child;
      }
      this.items[index] = last;
    }
    return first;
  }
}

function findPath(grid: Grid, start: Point, end: Point): Point[] | null {
  if (
    grid.rectangles.some(
      (rectangle) =>
        contains(rectangle, start.x, start.y) ||
        contains(rectangle, end.x, end.y),
    )
  )
    return null;
  const { xs, ys } = grid;
  const width = xs.length;
  const first = grid.rows.get(start.y)! * width + grid.columns.get(start.x)!;
  const target = grid.rows.get(end.y)! * width + grid.columns.get(end.x)!;
  // Each location has horizontal and vertical arrival states, so minimizing
  // length also discourages unnecessary turns without losing valid detours.
  const distance = new Float64Array(width * ys.length * 2).fill(Infinity);
  const previous = new Int32Array(distance.length).fill(-1);
  const frontier = new Frontier();
  distance[first * 2] = 0;
  frontier.push(
    first * 2,
    Math.abs(start.x - end.x) + Math.abs(start.y - end.y),
  );
  let item;
  while ((item = frontier.pop())) {
    const cell = item.state >> 1;
    const x = cell % width,
      y = Math.floor(cell / width);
    const remaining = Math.abs(xs[x] - end.x) + Math.abs(ys[y] - end.y);
    if (item.score > distance[item.state] + remaining) continue;
    if (cell === target) {
      const result: Point[] = [];
      for (let state = item.state; state !== -1; state = previous[state]) {
        const position = state >> 1;
        result.push({
          x: xs[position % width],
          y: ys[Math.floor(position / width)],
        });
      }
      return result.reverse();
    }
    const neighbors: [number, number, number][] = [];
    if (x > 0 && grid.horizontal[cell - 1])
      neighbors.push([cell - 1, 0, xs[x] - xs[x - 1]]);
    if (x + 1 < width && grid.horizontal[cell])
      neighbors.push([cell + 1, 0, xs[x + 1] - xs[x]]);
    if (y > 0 && grid.vertical[cell - width])
      neighbors.push([cell - width, 1, ys[y] - ys[y - 1]]);
    if (y + 1 < ys.length && grid.vertical[cell])
      neighbors.push([cell + width, 1, ys[y + 1] - ys[y]]);
    for (const [nextCell, direction, length] of neighbors) {
      const state = nextCell * 2 + direction;
      const cost =
        distance[item.state] +
        length +
        ((item.state & 1) === direction ? 0 : TURN_COST);
      if (cost >= distance[state]) continue;
      distance[state] = cost;
      previous[state] = item.state;
      const nextX = nextCell % width,
        nextY = Math.floor(nextCell / width);
      frontier.push(
        state,
        cost + Math.abs(xs[nextX] - end.x) + Math.abs(ys[nextY] - end.y),
      );
    }
  }
  return null;
}

function simplify(points: Point[]): Point[] {
  const result: Point[] = [];
  for (const point of points) {
    if (
      result.length &&
      result[result.length - 1].x === point.x &&
      result[result.length - 1].y === point.y
    )
      continue;
    while (result.length > 1) {
      const a = result[result.length - 2],
        b = result[result.length - 1];
      if ((a.x === b.x && b.x === point.x) || (a.y === b.y && b.y === point.y))
        result.pop();
      else break;
    }
    result.push(point);
  }
  return result;
}

function labelPoint(points: Point[]): Point {
  const segments = points.slice(1).map((point, index) => {
    const start = points[index];
    return {
      start,
      end: point,
      length: Math.abs(point.x - start.x) + Math.abs(point.y - start.y),
    };
  });
  const half =
    segments.reduce((total, segment) => total + segment.length, 0) / 2;
  let traversed = 0;
  let best = Infinity;
  let label = points[0];
  const horizontal = segments.some(
    (segment) => segment.start.y === segment.end.y && segment.length >= 48,
  );
  for (const segment of segments) {
    const eligible =
      !horizontal ||
      (segment.start.y === segment.end.y && segment.length >= 48);
    const delta = Math.abs(traversed + segment.length / 2 - half);
    if (eligible && delta < best) {
      best = delta;
      label = {
        x: (segment.start.x + segment.end.x) / 2,
        y: (segment.start.y + segment.end.y) / 2,
      };
    }
    traversed += segment.length;
  }
  return label;
}

function fallbackRoute({ source, target }: Anchors): EdgeRoute {
  const bend = Math.max(65, Math.abs(target.x - source.x) / 2);
  return {
    points: [source, target],
    // The symmetric cubic's t=0.5 point is also its endpoint midpoint.
    label: { x: (source.x + target.x) / 2, y: (source.y + target.y) / 2 },
    path: `M${source.x},${source.y} C${source.x + bend},${source.y} ${
      target.x - bend
    },${target.y} ${target.x},${target.y}`,
  };
}

export function routeEdges(
  nodes: GraphNode[],
  edges: GraphEdge[],
): Map<string, EdgeRoute> {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const rectangles = nodes.map((node) => nodeRectangle(node, 0));
  const anchors = new Map<string, Anchors>();
  for (const edge of edges) {
    const source = byId.get(edge.source),
      target = byId.get(edge.target);
    if (!source || !target) continue;
    const port = nodePorts(source).indexOf(edge.port);
    if (port < 0) continue;
    const from = {
      x: source.position.x + NODE_WIDTH,
      y:
        source.position.y +
        nodeHeaderHeight(source) +
        PORT_HEIGHT * (port + 0.5),
    };
    const to = { x: target.position.x, y: target.position.y + 54 };
    let exit = PORT_STUB,
      entry = PORT_STUB;
    for (const rectangle of rectangles) {
      if (
        from.y > rectangle.top &&
        from.y < rectangle.bottom &&
        rectangle.left >= from.x
      )
        exit = Math.min(exit, (rectangle.left - from.x) / 2);
      if (
        to.y > rectangle.top &&
        to.y < rectangle.bottom &&
        rectangle.right <= to.x
      )
        entry = Math.min(entry, (to.x - rectangle.right) / 2);
    }
    anchors.set(edge.id, {
      source: from,
      target: to,
      start: { x: from.x + exit, y: from.y },
      end: { x: to.x - entry, y: to.y },
    });
  }
  const routes = new Map<string, EdgeRoute>();
  if (!anchors.size) return routes;
  const points = [...anchors.values()];
  const grid = makeGrid(nodes, points, CLEARANCE);
  let tightGrid: Grid | undefined;
  for (const [id, anchor] of anchors) {
    if (
      rectangles.some(
        (rectangle) =>
          (anchor.source.y > rectangle.top &&
            anchor.source.y < rectangle.bottom &&
            anchor.source.x < rectangle.right &&
            anchor.start.x > rectangle.left) ||
          (anchor.target.y > rectangle.top &&
            anchor.target.y < rectangle.bottom &&
            anchor.end.x < rectangle.right &&
            anchor.target.x > rectangle.left),
      )
    ) {
      routes.set(id, fallbackRoute(anchor));
      continue;
    }
    let path = findPath(grid, anchor.start, anchor.end);
    if (!path) {
      // Closely placed cards can leave less than the preferred clearance.
      // Relax the spacing, never the actual card collision constraint.
      tightGrid ??= makeGrid(nodes, points, 0);
      path = findPath(tightGrid, anchor.start, anchor.end);
    }
    // Keep the original edge visible and selectable while cards overlap or a
    // port has no clear route. Moving the cards restores orthogonal routing.
    if (!path) {
      routes.set(id, fallbackRoute(anchor));
      continue;
    }
    const route = simplify([anchor.source, ...path, anchor.target]);
    routes.set(id, {
      points: route,
      label: labelPoint(route),
      path: route
        .map((point, index) => `${index ? "L" : "M"}${point.x},${point.y}`)
        .join(" "),
    });
  }
  return routes;
}
