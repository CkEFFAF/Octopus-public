import { describe, expect, it } from "vitest";
import { changedFileKey, mergeChangedFiles } from "./changedFiles";
import type { TurnFileChange } from "./turnFileChanges";
const change = (
  agentId: string,
  path: string,
  after: string,
  deviceId?: string,
): TurnFileChange => ({
  key: changedFileKey(path, agentId, deviceId),
  path,
  agentId,
  deviceId,
  confirmed: true,
  edits: [{ id: after, kind: "write", after }],
});
describe("merged changed file history", () => {
  it("deduplicates canonical workspace aliases and shows only selected turn edits for its files", () => {
    const history = [
      change("gpu", "/workspace/a.py", "old"),
      change("gpu", "b.py", "other"),
    ];
    const current = [change("gpu", "a.py", "selected")];
    const files = mergeChangedFiles(
      [{ path: "/workspace/a.py", agentId: "gpu" }],
      history,
      current,
      "gpu",
    );
    expect(files).toHaveLength(2);
    expect(files[0].edits[0].after).toBe("selected");
    expect(files[1].edits[0].after).toBe("other");
  });
  it("keeps different experts and devices with identical paths distinct", () => {
    const files = mergeChangedFiles(
      [],
      [
        change("one", "a.py", "1"),
        change("two", "a.py", "2"),
        change("one", "a.py", "3", "device"),
      ],
      [],
      "one",
    );
    expect(new Set(files.map((file) => file.key)).size).toBe(3);
  });
});
