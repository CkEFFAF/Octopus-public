import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, Terminal } from "lucide-react";
import { Button } from "antd";
import { useTranslation } from "react-i18next";
import type {
  ActivityNode,
  ActivitySnapshot,
} from "../../../api/modules/activity";
import { ActivityStatus } from "./TaskActivity";
import { activityGraphLayout } from "../utils/activityGraphLayout";
import styles from "./TaskActivity.module.less";

export default function TaskActivityGraph({
  snapshot,
  selected,
  onSelect,
  stale,
  timezone = "UTC",
}: {
  snapshot: ActivitySnapshot;
  selected: string;
  onSelect: (id: string) => void;
  stale: boolean;
  timezone?: string;
}) {
  const { t } = useTranslation();
  const [chosenRun, setChosenRun] = useState("");
  const runs = Array.from(
    snapshot.nodes
      .filter((n) => n.type === "plan" && n.run_id)
      .reduce(
        (values, node) =>
          values.set(
            node.run_id!,
            Math.max(values.get(node.run_id!) ?? 0, node.updated_at),
          ),
        new Map<string, number>(),
      ),
  ).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const activeRun = runs.some(([id]) => id === chosenRun)
    ? chosenRun
    : runs[0]?.[0];
  if (activeRun) {
    const nodes = snapshot.nodes.filter((n) => n.run_id === activeRun);
    const ids = new Set(nodes.map((n) => n.id));
    snapshot = {
      ...snapshot,
      nodes,
      edges: snapshot.edges.filter((e) => ids.has(e.from) && ids.has(e.to)),
    };
  }
  const viewport = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const manualScale = useRef(false);
  const [expanded, setExpanded] = useState("");
  const structure = JSON.stringify({
    nodes: snapshot.nodes
      .filter((n) => n.type === "plan")
      .map((n) => n.id)
      .sort(),
    edges: snapshot.edges.filter((e) => e.kind === "depends_on"),
  });
  const layout = useMemo(() => activityGraphLayout(snapshot), [structure]); // eslint-disable-line react-hooks/exhaustive-deps
  function fit() {
    const host = viewport.current;
    if (host?.clientWidth && host.clientHeight)
      setScale(
        Math.min(
          1,
          // Narrow panes keep readable labels; zooming out remains explicit.
          host.clientWidth < 480 ? 1 : host.clientWidth / layout.width,
          host.clientHeight / layout.height,
        ),
      );
  }
  useEffect(() => {
    manualScale.current = false;
    const host = viewport.current;
    if (!host) return;
    const observer = new ResizeObserver(() => {
      if (!manualScale.current) fit();
    });
    observer.observe(host);
    fit();
    return () => observer.disconnect();
  }, [layout]); // eslint-disable-line react-hooks/exhaustive-deps
  const plans = snapshot.nodes.filter((n) => n.type === "plan");
  const byId = new Map(snapshot.nodes.map((n) => [n.id, n]));
  function children(identity: string, all = false) {
    const visited = new Set<string>();
    const queue = [identity];
    while (queue.length) {
      const from = queue.shift()!;
      for (const edge of snapshot.edges.filter(
        (e) => e.kind === "contains" && e.from === from,
      )) {
        if (!visited.has(edge.to)) {
          visited.add(edge.to);
          queue.push(edge.to);
        }
      }
    }
    return snapshot.nodes
      .filter(
        (n) =>
          visited.has(n.id) &&
          (all || ["subagent", "delegation", "job"].includes(n.type)),
      )
      .sort(
        (a, b) =>
          Number(b.status === "running") - Number(a.status === "running") ||
          a.id.localeCompare(b.id),
      );
  }
  const linked = new Set(
    plans.flatMap((plan) => children(plan.id, true).map((n) => n.id)),
  );
  const unlinked = snapshot.nodes.filter(
    (n) => n.type !== "plan" && !linked.has(n.id),
  );
  const row = (node: ActivityNode) => (
    <button
      key={node.id}
      className={`${styles.graphActivity} ${
        selected === node.id ? styles.selected : ""
      }`}
      onClick={(e) => {
        e.stopPropagation();
        onSelect(node.id);
      }}
    >
      {node.type === "job" ? <Terminal size={13} /> : <Bot size={13} />}
      <span title={node.name}>
        {node.type === "job" ? t("workspace0034.nodeType.job") : node.name}
      </span>
      <ActivityStatus node={node} stale={stale} />
    </button>
  );
  return (
    <div
      style={{
        height: "100%",
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
      }}
    >
      <div className={styles.graphToolbar}>
        {runs.length > 1 && (
          <select
            className={styles.graphRunSelect}
            aria-label={t("workspace0034.executionRun")}
            value={activeRun}
            onChange={(e) => {
              setChosenRun(e.target.value);
              onSelect("");
            }}
          >
            {runs.map(([id, at], index) => (
              <option key={id} value={id}>
                {t(
                  index === 0
                    ? "workspace0034.latestExecution"
                    : "workspace0034.priorExecution",
                )}{" "}
                ·{" "}
                {new Date(at * 1000).toLocaleString(undefined, {
                  timeZone: timezone,
                  month: "2-digit",
                  day: "2-digit",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </option>
            ))}
          </select>
        )}
        <Button
          onClick={() => {
            manualScale.current = true;
            setScale((s) => Math.min(3, s + 0.2));
          }}
        >
          +
        </Button>
        <Button
          onClick={() => {
            manualScale.current = true;
            setScale((s) => Math.max(0.3, s - 0.2));
          }}
        >
          −
        </Button>
        <Button
          onClick={() => {
            manualScale.current = false;
            fit();
          }}
        >
          {t("workspace0034.fit")}
        </Button>
        <small>{t("workspace0034.edgeLegend")}</small>
      </div>
      <div ref={viewport} style={{ overflow: "auto", flex: 1, minHeight: 220 }}>
        <svg
          width={layout.width * scale}
          height={layout.height * scale}
          role="group"
          aria-label={t("workspace0034.dag")}
        >
          <g transform={`scale(${scale})`}>
            <defs>
              <marker
                id="activity-arrow"
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M0 0 L10 5 L0 10z" fill="#8292aa" />
              </marker>
            </defs>
            {snapshot.edges
              .filter((e) => e.kind === "depends_on")
              .map((edge) => {
                const a = layout.positions[edge.from],
                  b = layout.positions[edge.to];
                return a && b ? (
                  <path
                    key={`${edge.from}:${edge.to}`}
                    d={`M${a.x + 220},${a.y + 79} C${a.x + 250},${a.y + 79} ${
                      b.x - 30
                    },${b.y + 79} ${b.x},${b.y + 79}`}
                    fill="none"
                    stroke="#8292aa"
                    strokeWidth={1.6}
                    markerEnd="url(#activity-arrow)"
                  />
                ) : null;
              })}
            {plans.map((plan) => {
              const p = layout.positions[plan.id];
              if (!p) return null;
              const activities = children(plan.id);
              return (
                <foreignObject
                  key={plan.id}
                  x={p.x}
                  y={p.y}
                  width={220}
                  height={158}
                >
                  <div
                    className={`${styles.planCard} ${
                      selected === plan.id ? styles.selected : ""
                    }`}
                  >
                    <button
                      className={styles.planTitle}
                      onClick={() => onSelect(plan.id)}
                    >
                      <strong>{plan.name}</strong>
                      <ActivityStatus node={plan} stale={stale} />
                    </button>
                    <div className={styles.planExecutors}>
                      {activities.slice(0, 3).map(row)}
                      {!activities.length && (
                        <small>{t("workspace0034.noLinkedExecution")}</small>
                      )}
                      {activities.length > 3 && (
                        <button
                          className={styles.graphMore}
                          onClick={() => setExpanded(plan.id)}
                        >
                          {t("workspace0034.taskActivityMore", {
                            count: activities.length,
                          })}
                        </button>
                      )}
                    </div>
                  </div>
                </foreignObject>
              );
            })}
          </g>
        </svg>
      </div>
      {expanded && byId.has(expanded) && (
        <section className={styles.graphExpanded}>
          <div>
            <b>{byId.get(expanded)!.name}</b>
            <Button type="text" onClick={() => setExpanded("")}>
              {t("common.close")}
            </Button>
          </div>
          {children(expanded).map(row)}
        </section>
      )}
      {unlinked.length > 0 && (
        <details>
          <summary>
            {t("workspace0034.unlinkedActivities", { count: unlinked.length })}
          </summary>
          <div className={styles.list}>{unlinked.map(row)}</div>
        </details>
      )}
    </div>
  );
}
