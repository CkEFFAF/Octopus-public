import { describe, expect, it } from "vitest";
import { parseDiff, pairDiff, diffStats, statusFilePath } from "./gitDiff";

describe("Git diff rendering", () => {
  it("decodes escaped names and only splits rename arrows outside quotes", () => {
    expect(statusFilePath('"note -> name.txt"')).toBe("note -> name.txt");
    expect(statusFilePath('"old name.txt" -> "new name.txt"')).toBe(
      "new name.txt",
    );
    expect(statusFilePath("说明.md")).toBe("说明.md");
  });
  const patch =
    "diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -48,2 +48,3 @@\n same\n-old\n+new\n+extra";
  it("uses real source line numbers and excludes metadata from totals", () => {
    expect(parseDiff(patch).slice(1)).toEqual([
      { text: "same", old: 48, next: 48, kind: "context" },
      { text: "old", old: 49, kind: "removed" },
      { text: "new", next: 49, kind: "added" },
      { text: "extra", next: 50, kind: "added" },
    ]);
    expect(diffStats(patch)).toEqual({ added: 2, removed: 1 });
  });
  it("pairs replacements and leaves an empty left cell for extra additions", () => {
    const rows = pairDiff(parseDiff(patch));
    expect(rows[2].left?.text).toBe("old");
    expect(rows[2].right?.text).toBe("new");
    expect(rows[3].left).toBeUndefined();
    expect(rows[3].right?.next).toBe(50);
  });
});
