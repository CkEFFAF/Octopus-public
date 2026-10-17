import { describe, expect, it } from "vitest";

import { resolveTurnMcpServersPayload } from "./resolveTurnMcpServersPayload";

describe("resolveTurnMcpServersPayload (0025.1 AC-D01–D03)", () => {
  it("AC-D01: cold empty omits key (undefined)", () => {
    expect(resolveTurnMcpServersPayload([], {})).toBeUndefined();
    expect(
      resolveTurnMcpServersPayload([], { restricted: false, optedOut: false }),
    ).toBeUndefined();
  });

  it("AC-D02: user clear sends []", () => {
    expect(
      resolveTurnMcpServersPayload([], { optedOut: true }),
    ).toEqual([]);
  });

  it("AC-D03: ask/plan restricted sends []", () => {
    expect(
      resolveTurnMcpServersPayload(["a"], { restricted: true }),
    ).toEqual([]);
    expect(
      resolveTurnMcpServersPayload([], { restricted: true }),
    ).toEqual([]);
  });

  it("non-empty picks pass through (even if previously opted out flag stale)", () => {
    expect(
      resolveTurnMcpServersPayload(["a", "b"], { optedOut: true }),
    ).toEqual(["a", "b"]);
  });

  it("team-style restricted empty is [] not omit", () => {
    expect(
      resolveTurnMcpServersPayload([], { restricted: true, optedOut: true }),
    ).toEqual([]);
  });
});
