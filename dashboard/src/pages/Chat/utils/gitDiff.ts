export type DiffLine = {
  text: string;
  old?: number;
  next?: number;
  kind: "context" | "added" | "removed" | "hunk";
};

export function decodeGitPath(value: string): string {
  if (!value.startsWith('"')) return value;
  // core.quotepath=false keeps UTF-8 names intact; Git still quotes escapes/spaces.
  try {
    return JSON.parse(value) as string;
  } catch {
    return value;
  }
}

export function statusFilePath(value: string): string {
  let quoted = false;
  for (let i = 0; i < value.length; i++) {
    if (value[i] === "\\" && quoted) {
      i++;
      continue;
    }
    if (value[i] === '"') quoted = !quoted;
    if (!quoted && value.slice(i, i + 4) === " -> ")
      return decodeGitPath(value.slice(i + 4));
  }
  return decodeGitPath(value);
}

export function parseDiff(value: string): DiffLine[] {
  let old = 0;
  let next = 0;
  let inHunk = false;
  const result: DiffLine[] = [];
  for (const line of value.split("\n")) {
    const match = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (match) {
      old = Number(match[1]);
      next = Number(match[2]);
      inHunk = true;
      result.push({ text: line, kind: "hunk" });
    } else if (inHunk && line.startsWith("+")) {
      result.push({ text: line.slice(1), next: next++, kind: "added" });
    } else if (inHunk && line.startsWith("-")) {
      result.push({ text: line.slice(1), old: old++, kind: "removed" });
    } else if (inHunk && line.startsWith(" ")) {
      result.push({
        text: line.slice(1),
        old: old++,
        next: next++,
        kind: "context",
      });
    }
  }
  return result;
}

export function pairDiff(
  lines: DiffLine[],
): { left?: DiffLine; right?: DiffLine; hunk?: string }[] {
  const rows: { left?: DiffLine; right?: DiffLine; hunk?: string }[] = [];
  let removed: DiffLine[] = [];
  let added: DiffLine[] = [];
  const flush = () => {
    for (let i = 0; i < Math.max(removed.length, added.length); i++)
      rows.push({ left: removed[i], right: added[i] });
    removed = [];
    added = [];
  };
  for (const line of lines) {
    if (line.kind === "removed") removed.push(line);
    else if (line.kind === "added") added.push(line);
    else {
      flush();
      rows.push(
        line.kind === "hunk"
          ? { hunk: line.text }
          : { left: line, right: line },
      );
    }
  }
  flush();
  return rows;
}

export function diffStats(value: string) {
  const lines = parseDiff(value);
  return {
    added: lines.filter((line) => line.kind === "added").length,
    removed: lines.filter((line) => line.kind === "removed").length,
  };
}
