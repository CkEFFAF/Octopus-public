import { describe, expect, it } from "vitest";
import { applyWorkMode } from "./workMode";

describe("applyWorkMode", () => {
  it("keeps native permission modes unchanged", () => {
    expect(applyWorkMode("task", "plan", "zh")).toBe("task");
    expect(applyWorkMode("task", "agentic", "zh")).toBe("task");
  });

  it("adds a visible, nonduplicated workflow request", () => {
    const text = applyWorkMode("fix the crash", "debug", "en");
    expect(text).toContain("Reproduce the issue");
    expect(text).toContain("fix the crash");
    expect(applyWorkMode(text, "debug", "en")).toBe(text);
  });
});
