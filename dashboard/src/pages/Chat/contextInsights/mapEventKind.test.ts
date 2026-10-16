import { describe, expect, it } from "vitest";
import { isCompactMark, mapTrajectoryKind } from "./mapEventKind";

describe("mapTrajectoryKind", () => {
  it("maps trajectory kinds", () => {
    expect(mapTrajectoryKind("compacted")).toBe("compact");
    expect(mapTrajectoryKind("context")).toBe("inject");
    expect(mapTrajectoryKind("user")).toBe("user");
  });

  it("treats summarization as compact", () => {
    expect(
      mapTrajectoryKind("assistant", {
        transformation: { kind: "summarization" },
      }),
    ).toBe("compact");
    expect(isCompactMark("compacted")).toBe(true);
  });
});
