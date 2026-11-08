import { afterEach, describe, expect, it, vi } from "vitest";
import { getSnapshot, ingestHarnessChunk, removeSession } from "./chatStore";
import { parseHarnessChunk } from "../../../utils/parseHarnessChunk";
vi.mock("../../../i18n", () => ({ default: { t: (key: string) => key } }));
const session = "synthetic-model-routing";
afterEach(() => removeSession(session));
describe("actual model routing feedback", () => {
  it.each(["WebSocket", "SSE"])(
    "retains the selected model and reason over %s",
    (transport) => {
      const chunk = {
        type: "model_route" as const,
        task: "coding" as const,
        model: "Owned/coder",
        source: "task" as const,
        reason: "task_model",
        available: true,
      };
      const parsed =
        transport === "SSE"
          ? parseHarnessChunk("data: " + JSON.stringify(chunk))!
          : chunk;
      ingestHarnessChunk(session, parsed);
      expect(getSnapshot(session).modelRoute).toMatchObject({
        model: "Owned/coder",
        reason: "task_model",
        task: "coding",
      });
      ingestHarnessChunk(session, {
        type: "run_phase",
        run_id: "run",
        phase: "preparing",
      });
      expect(getSnapshot(session).modelRoute?.model).toBe("Owned/coder");
      ingestHarnessChunk(session, { type: "done" });
      expect(getSnapshot(session).modelRoute?.model).toBe("Owned/coder");
    },
  );
  it("does not interpret malformed routing as a valid decision", () => {
    expect(
      parseHarnessChunk(
        'data: {"type":"model_route","task":"unknown","model":"p/m"}',
      ),
    ).toBeNull();
    expect(
      parseHarnessChunk(
        'data: {"type":"model_route","task":"chat","model":17}',
      ),
    ).toBeNull();
  });
});
