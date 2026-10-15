import { describe, expect, it } from "vitest";
import {
  executionScope,
  getExecutionSelection,
  setExecutionSelection,
  executionSelectionReady,
  setExecutionSelectionStatus,
} from "./deviceTarget";

describe("execution selection", () => {
  it("allows new-thread inheritance and requires restoration for existing threads", () => {
    const scope = executionScope("new-expert", "new-thread");
    expect(executionSelectionReady(scope, null)).toBe(true);
    expect(executionSelectionReady(scope, "__new__")).toBe(true);
    expect(executionSelectionReady(scope, "new-thread")).toBe(false);
    setExecutionSelectionStatus(scope, "ready");
    expect(executionSelectionReady(scope, "new-thread")).toBe(true);
  });
  it("keeps targets and modes separate across experts and threads", () => {
    const a = executionScope("expert", "thread-a");
    const b = executionScope("expert", "thread-b");
    const c = executionScope("other-expert", "thread-a");
    setExecutionSelection(a, { deviceId: "gpu", workMode: "debug" });
    setExecutionSelection(b, { deviceId: "laptop", workMode: "plan" });
    expect(getExecutionSelection(a)).toEqual({
      deviceId: "gpu",
      workMode: "debug",
    });
    expect(getExecutionSelection(b)).toEqual({
      deviceId: "laptop",
      workMode: "plan",
    });
    expect(getExecutionSelection(c)).toEqual({
      deviceId: "",
      workMode: "agentic",
    });
  });
});
