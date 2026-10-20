import type { ActivitySnapshot } from "../../../api/modules/activity";

export function activityGraphLayout(
  snapshot: Pick<ActivitySnapshot, "nodes" | "edges">,
) {
  const ids = snapshot.nodes
    .filter((n) => n.type === "plan")
    .map((n) => n.id)
    .sort();
  const known = new Set(ids);
  const parents = new Map(ids.map((id) => [id, [] as string[]]));
  snapshot.edges
    .filter(
      (e) => e.kind === "depends_on" && known.has(e.from) && known.has(e.to),
    )
    .forEach((e) => parents.get(e.to)!.push(e.from));
  const ranks = new Map<string, number>();
  function rank(id: string, path = new Set<string>()): number {
    if (ranks.has(id)) return ranks.get(id)!;
    if (path.has(id)) return 0;
    const next = new Set(path).add(id);
    const values = parents.get(id) ?? [];
    const value = values.length
      ? Math.max(...values.map((parent) => rank(parent, next))) + 1
      : 0;
    ranks.set(id, value);
    return value;
  }
  ids.forEach((id) => rank(id));
  const rows = new Map<number, number>();
  const positions: Record<string, { x: number; y: number }> = {};
  ids.forEach((id) => {
    const column = ranks.get(id)!;
    const row = rows.get(column) ?? 0;
    rows.set(column, row + 1);
    positions[id] = { x: 20 + column * 280, y: 20 + row * 184 };
  });
  const maxRows = Math.max(1, ...rows.values());
  ids.forEach((id) => {
    positions[id].y += (maxRows - (rows.get(ranks.get(id)!) ?? 1)) * 92;
  });
  return {
    positions,
    width: Math.max(400, (Math.max(0, ...ranks.values()) + 1) * 280),
    height: Math.max(198, maxRows * 184 + 20),
  };
}
