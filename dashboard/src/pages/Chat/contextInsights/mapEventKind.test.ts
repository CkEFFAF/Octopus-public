import { describe, expect, it } from "vitest";
import {
  isCompactMark,
  mapRunEventKind,
  mapTrajectoryKind,
} from "./mapEventKind";

describe("mapTrajectoryKind", () => {
  it("maps trajectory kinds", () => {
    expect(mapTrajectoryKind("compacted")).toBe("compact");
    expect(mapTrajectoryKind("context")).toBe("inject");
    expect(mapTrajectoryKind("system")).toBe("inject");
    expect(mapTrajectoryKind("user")).toBe("user");
    expect(mapTrajectoryKind("assistant")).toBe("assistant");
    expect(mapTrajectoryKind("tool")).toBe("tool");
    expect(mapTrajectoryKind("mystery")).toBe("other");
  });

  it("treats summarization as compact and prune flags", () => {
    expect(
      mapTrajectoryKind("assistant", {
        transformation: { kind: "summarization" },
      }),
    ).toBe("compact");
    expect(mapTrajectoryKind("assistant", { prune: true })).toBe("prune");
    expect(mapTrajectoryKind("assistant", { prune: "yes" })).toBe("prune");
    expect(isCompactMark("compacted")).toBe(true);
  });

  it("maps producer/model and mode/switch like Python", () => {
    expect(mapTrajectoryKind("assistant", { producer: "model-router" })).toBe(
      "model",
    );
    expect(mapTrajectoryKind("mode")).toBe("mode");
    expect(mapTrajectoryKind("switch")).toBe("switch");
  });
});

describe("mapRunEventKind", () => {
  it("aligns with Python run_event map", () => {
    expect(mapRunEventKind("model")).toBe("model");
    expect(mapRunEventKind("device")).toBe("switch");
    expect(mapRunEventKind("workflow")).toBe("mode");
    expect(mapRunEventKind("custom", { work_mode: "ask" })).toBe("mode");
  });
});
