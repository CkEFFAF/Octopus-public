import { afterEach, describe, expect, it, vi } from "vitest";
import { getSnapshot, ingestHarnessChunk, removeSession } from "./chatStore";
import {
  parseHarnessChunk,
  type UsageChunk,
} from "../../../utils/parseHarnessChunk";

vi.mock("../../../i18n", () => ({ default: { t: (key: string) => key } }));
const session = "synthetic-cache-metric-availability";
afterEach(() => removeSession(session));
describe("cache usage availability", () => {
  it("honors unknown provenance even when the runtime supplies numeric zero", () => {
    ingestHarnessChunk(session, {
      type: "usage",
      call_id: "canonical",
      usage: {
        input_tokens: 100,
        output_tokens: 1,
        cache_read_tokens: 0,
        cache_metrics_reported: false,
      },
    });
    expect(getSnapshot(session).runUsage?.cache_read_tokens).toBeUndefined();
  });
  it.each(["WebSocket", "SSE"])(
    "preserves missing metrics and mixed calls over %s",
    (transport) => {
      const send = (raw: UsageChunk) =>
        ingestHarnessChunk(
          session,
          transport === "SSE"
            ? parseHarnessChunk("data: " + JSON.stringify(raw))!
            : raw,
        );
      send({
        type: "usage",
        call_id: "a",
        usage: { input_tokens: 100, output_tokens: 1, cache_read_tokens: 80 },
      });
      expect(getSnapshot(session).runUsage?.cache_read_tokens).toBe(80);
      send({
        type: "usage",
        call_id: "b",
        usage: { input_tokens: 120, output_tokens: 2 },
      });
      expect(getSnapshot(session).runUsage?.input_tokens).toBe(220);
      expect(getSnapshot(session).runUsage?.cache_read_tokens).toBeUndefined();
      // An updated sample replaces the same call, so later reported metrics are usable.
      send({
        type: "usage",
        call_id: "b",
        usage: { input_tokens: 120, output_tokens: 2, cache_read_tokens: 0 },
      });
      expect(getSnapshot(session).runUsage?.cache_read_tokens).toBe(80);
    },
  );
  it("keeps legacy events unknown after a missing sample", () => {
    for (const usage of [
      { input_tokens: 100, output_tokens: 1 },
      { input_tokens: 120, output_tokens: 2, cache_read_tokens: 90 },
    ])
      ingestHarnessChunk(session, { type: "usage", usage });
    expect(getSnapshot(session).runUsage?.input_tokens).toBe(220);
    expect(getSnapshot(session).runUsage?.cache_read_tokens).toBeUndefined();
  });
});
