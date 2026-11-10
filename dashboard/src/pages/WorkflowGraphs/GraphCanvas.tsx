import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { Button, Space } from "antd";
import { Expand, Minus, Plus } from "lucide-react";
import type {
  Activation,
  GraphDefinition,
  GraphEdge,
} from "../../api/modules/workflowGraphs";
import {
  NODE_WIDTH,
  PORT_HEIGHT,
  NodeIcon,
  nodeHeaderHeight,
  nodePorts,
  nodePreview,
} from "./nodePresentation";

export function GraphCanvas({
  graph,
  selected,
  onSelect,
  onChange,
  activations,
  tr,
  readOnly = false,
}: {
  graph: GraphDefinition;
  selected: string;
  onSelect: (id: string) => void;
  onChange: (graph: GraphDefinition) => void;
  activations: Activation[];
  tr: (key: string) => string;
  readOnly?: boolean;
}) {
  const root = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ x: 64, y: 64, scale: 1 });
  const initialFit = useRef(false);
  const viewRef = useRef(view);
  viewRef.current = view;
  const [connecting, setConnecting] = useState<{
    node: string;
    port: GraphEdge["port"];
  } | null>(null);
  const [moving, setMoving] = useState<{
    id: string;
    x: number;
    y: number;
  } | null>(null);
  const drag = useRef<{
    id: string;
    x: number;
    y: number;
    baseX: number;
    baseY: number;
  } | null>(null);
  const latest = new Map(
    activations.map((item) => [item.node_id, item.status]),
  );
  const nodes = graph.nodes.map((node) =>
    moving?.id === node.id
      ? { ...node, position: { x: moving.x, y: moving.y } }
      : node,
  );
  const connect = (target: string) => {
    if (!connecting || readOnly) return;
    onChange({
      ...graph,
      edges: [
        ...graph.edges,
        {
          id: `edge_${crypto.randomUUID().slice(0, 8)}`,
          source: connecting.node,
          target,
          port: connecting.port,
        },
      ],
    });
    setConnecting(null);
  };
  const fit = useCallback(() => {
    const nodes = graph.nodes;
    if (
      !root.current ||
      !nodes.length ||
      root.current.clientWidth < 100 ||
      root.current.clientHeight < 100
    )
      return;
    const x = Math.min(...nodes.map((n) => n.position.x)),
      y = Math.min(...nodes.map((n) => n.position.y));
    const w = Math.max(...nodes.map((n) => n.position.x)) - x + NODE_WIDTH,
      h =
        Math.max(
          ...nodes.map(
            (n) =>
              n.position.y +
              nodeHeaderHeight(n) +
              nodePorts(n).length * PORT_HEIGHT,
          ),
        ) - y;
    const scale = Math.min(
      1,
      (root.current.clientWidth - 128) / w,
      (root.current.clientHeight - 160) / h,
    );
    setView({
      x: 64 - x * scale,
      y: 104 - y * scale,
      scale: Math.max(0.15, scale),
    });
  }, [graph.nodes]);
  useEffect(() => {
    if (!initialFit.current && root.current?.clientWidth) {
      fit();
      initialFit.current = true;
    }
  }, [fit]);
  useEffect(() => {
    const node = graph.nodes.find((item) => item.id === selected),
      bounds = root.current,
      v = viewRef.current;
    if (!node || !bounds || bounds.clientWidth < 100 || drag.current) return;
    const left = node.position.x * v.scale + v.x,
      top = node.position.y * v.scale + v.y;
    if (
      left < 0 ||
      left + NODE_WIDTH * v.scale > bounds.clientWidth ||
      top < 0 ||
      top + 220 * v.scale > bounds.clientHeight
    )
      setView({
        ...v,
        x:
          bounds.clientWidth / 2 - (node.position.x + NODE_WIDTH / 2) * v.scale,
        y: bounds.clientHeight / 2 - (node.position.y + 100) * v.scale,
      });
  }, [selected, graph.nodes]);
  return (
    <div
      className="wg-canvas"
      ref={root}
      tabIndex={0}
      aria-label={tr("canvas")}
      onWheel={(event) => {
        event.preventDefault();
        if (event.ctrlKey || event.metaKey)
          setView((v) => ({
            ...v,
            scale: Math.max(
              0.15,
              Math.min(2, v.scale * (event.deltaY > 0 ? 0.9 : 1.1)),
            ),
          }));
        else
          setView((v) => ({
            ...v,
            x: v.x - event.deltaX,
            y: v.y - event.deltaY,
          }));
      }}
      onPointerDown={(event) => {
        if (event.target !== event.currentTarget) return;
        onSelect("");
        drag.current = {
          id: "",
          x: event.clientX,
          y: event.clientY,
          baseX: view.x,
          baseY: view.y,
        };
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={(event) => {
        const d = drag.current;
        if (!d) return;
        const dx = event.clientX - d.x,
          dy = event.clientY - d.y;
        if (d.id)
          setMoving({
            id: d.id,
            x: d.baseX + dx / view.scale,
            y: d.baseY + dy / view.scale,
          });
        else setView((v) => ({ ...v, x: d.baseX + dx, y: d.baseY + dy }));
      }}
      onPointerUp={() => {
        if (moving)
          onChange({
            ...graph,
            nodes: graph.nodes.map((n) =>
              n.id === moving.id
                ? { ...n, position: { x: moving.x, y: moving.y } }
                : n,
            ),
          });
        drag.current = null;
        setMoving(null);
      }}
      onPointerCancel={() => {
        drag.current = null;
        setMoving(null);
      }}
      onKeyDown={(event) => {
        if (readOnly) return;
        if (event.key === "Escape") setConnecting(null);
      }}
    >
      <div
        className="wg-world"
        style={{
          transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
        }}
      >
        <svg className="wg-edges" role="group" aria-label={tr("connections")}>
          <defs>
            <marker
              id="wg-arrow"
              markerWidth="8"
              markerHeight="8"
              refX="7"
              refY="3"
              orient="auto"
            >
              <path d="M0,0 L7,3 L0,6" fill="currentColor" />
            </marker>
          </defs>
          {graph.edges.map((edge) => {
            const source = nodes.find((n) => n.id === edge.source),
              target = nodes.find((n) => n.id === edge.target);
            if (!source || !target) return null;
            const x = source.position.x + NODE_WIDTH,
              y =
                source.position.y +
                nodeHeaderHeight(source) +
                PORT_HEIGHT * (nodePorts(source).indexOf(edge.port) + 0.5),
              tx = target.position.x,
              ty = target.position.y + 54;
            const bend = Math.max(65, Math.abs(tx - x) / 2),
              d = `M${x},${y} C${x + bend},${y} ${tx - bend},${ty} ${tx},${ty}`;
            return (
              <g
                key={edge.id}
                role="button"
                tabIndex={0}
                aria-label={`${source.label} ${edge.port} ${target.label}`}
                className={selected === edge.id ? "selected" : ""}
                onClick={() => onSelect(edge.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(edge.id);
                  }
                }}
              >
                <path className="wg-edge-hit" d={d} />
                <path className="wg-edge" d={d} markerEnd="url(#wg-arrow)" />
                <text x={(x + tx) / 2} y={(y + ty) / 2 - 10}>
                  {edge.label ||
                    (edge.port === "next" ? "" : tr(`port.${edge.port}`))}
                </text>
              </g>
            );
          })}
        </svg>
        {nodes.map((node) => (
          <section
            key={node.id}
            className={`wg-node ${
              selected === node.id ? "selected" : ""
            } kind-${node.kind} state-${latest.get(node.id) || "draft"}`}
            style={
              {
                left: node.position.x,
                top: node.position.y,
                "--wg-head-height": `${nodeHeaderHeight(node)}px`,
              } as CSSProperties
            }
            aria-label={node.label}
          >
            <button
              className="wg-node-heading"
              onClick={() => onSelect(node.id)}
              onPointerDown={(event) => {
                event.stopPropagation();
                onSelect(node.id);
                if (readOnly) return;
                drag.current = {
                  id: node.id,
                  x: event.clientX,
                  y: event.clientY,
                  baseX: node.position.x,
                  baseY: node.position.y,
                };
                root.current?.setPointerCapture(event.pointerId);
              }}
              onKeyDown={(event) => {
                if (readOnly) return;
                const delta: Record<string, [number, number]> = {
                  ArrowLeft: [-20, 0],
                  ArrowRight: [20, 0],
                  ArrowUp: [0, -20],
                  ArrowDown: [0, 20],
                };
                if (delta[event.key]) {
                  event.preventDefault();
                  const [x, y] = delta[event.key];
                  onChange({
                    ...graph,
                    nodes: graph.nodes.map((n) =>
                      n.id === node.id
                        ? {
                            ...n,
                            position: {
                              x: n.position.x + x,
                              y: n.position.y + y,
                            },
                          }
                        : n,
                    ),
                  });
                }
              }}
            >
              <span className="wg-node-icon">
                <NodeIcon kind={node.kind} size={22} />
              </span>
              <span className="wg-node-title">
                <span className="wg-kind">{tr(`kind.${node.kind}`)}</span>
                <strong title={node.label}>{node.label}</strong>
              </span>
              {latest.has(node.id) && (
                <span
                  className="wg-node-state"
                  title={tr(`status.${latest.get(node.id)}`)}
                >
                  <i />
                </span>
              )}
              <span
                className={`wg-node-preview ${
                  node.kind === "script" ? "is-command" : ""
                }`}
              >
                {nodePreview(node, tr)}
              </span>
              {node.kind === "agent" && (
                <span className="wg-node-context">
                  <span>
                    {tr(
                      node.context?.before?.session === "new"
                        ? "nodeNewSession"
                        : "nodeCurrentSession",
                    )}
                  </span>
                  <span>
                    {node.context?.before?.history === "recent"
                      ? `${node.context.before.recent_turns || 8} ${tr(
                          "recentTurnsUnit",
                        )}`
                      : tr(
                          node.context?.before?.history === "empty"
                            ? "empty"
                            : "inherit",
                        )}
                  </span>
                </span>
              )}
            </button>
            {!readOnly && node.kind !== "entry" && (
              <button
                className="wg-input-port"
                aria-label={`${tr("connectTo")} ${node.label}`}
                title={tr("connectTo")}
                onPointerUp={(event) => {
                  event.stopPropagation();
                  connect(node.id);
                }}
                onClick={() => connect(node.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    connect(node.id);
                  }
                }}
              />
            )}
            <div className="wg-ports">
              {nodePorts(node).map((port) => (
                <button
                  key={port}
                  disabled={readOnly}
                  className={`wg-port-${port}`}
                  aria-pressed={
                    connecting?.node === node.id && connecting.port === port
                  }
                  onClick={() =>
                    setConnecting({
                      node: node.id,
                      port: port as GraphEdge["port"],
                    })
                  }
                >
                  {tr(`port.${port}`)}
                  <i />
                </button>
              ))}
            </div>
          </section>
        ))}
      </div>
      {connecting && (
        <div className="wg-connect-hint" role="status">
          {tr("connectionHint")}{" "}
          <Button size="small" onClick={() => setConnecting(null)}>
            {tr("cancel")}
          </Button>
        </div>
      )}
      <div className="wg-canvas-controls">
        <Space.Compact>
          <Button
            aria-label={tr("zoomOut")}
            icon={<Minus size={15} />}
            onClick={() =>
              setView((v) => ({ ...v, scale: Math.max(0.15, v.scale / 1.2) }))
            }
          />
          <Button onClick={() => setView((v) => ({ ...v, scale: 1 }))}>
            {Math.round(view.scale * 100)}%
          </Button>
          <Button
            aria-label={tr("zoomIn")}
            icon={<Plus size={15} />}
            onClick={() =>
              setView((v) => ({ ...v, scale: Math.min(2, v.scale * 1.2) }))
            }
          />
          <Button
            aria-label={tr("fit")}
            icon={<Expand size={15} />}
            onClick={fit}
          />
        </Space.Compact>
      </div>
    </div>
  );
}
