import { afterEach, describe, expect, it, vi } from "vitest";
import { getAuthToken, request, setAuthToken } from "./request";

vi.mock("./config", () => ({ getApiUrl: (path: string) => `/api${path}` }));
vi.mock("../i18n", () => ({ default: { language: "zh" } }));

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
});

describe("conditional response validation", () => {
  it("renews authentication on an opted-in 304 without decoding a body", async () => {
    setAuthToken("old");
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(null, {
            status: 304,
            headers: { "X-Octop-Access-Token": "renewed" },
          }),
      ),
    );
    const result = await request(
      "/agents/expert/threads/thread/history",
      {},
      { onNotModified: () => null },
    );
    expect(result).toBeNull();
    expect(getAuthToken()).toBe("renewed");
  });

  it("does not treat an unexpected 304 as an empty successful response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 304 })),
    );
    await expect(request("/agents")).rejects.toThrow("304");
  });
});
