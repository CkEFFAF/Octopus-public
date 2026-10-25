import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./config", () => ({ getApiUrl: (path: string) => `/api${path}` }));
vi.mock("../i18n", () => ({ default: { language: "zh" } }));

describe("responses from a previous login", () => {
  let api: typeof import("./request");
  const replace = vi.fn();

  beforeEach(async () => {
    vi.resetModules();
    localStorage.clear();
    sessionStorage.clear();
    replace.mockClear();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { pathname: "/chat", replace },
    });
    api = await import("./request");
    api.setAuthToken("alice", false);
  });

  const transports = [
    "request",
    "requestBlob",
    "probeAuthResource",
    "requestStream",
  ] as const;

  it.each(transports)(
    "%s cannot restore a logged-out session",
    async (transport) => {
      let respond!: (response: Response) => void;
      vi.stubGlobal(
        "fetch",
        vi.fn(
          () =>
            new Promise<Response>((resolve) => {
              respond = resolve;
            }),
        ),
      );
      const pending = api[transport]("/agents");
      api.clearAuthToken();
      respond(
        new Response("{}", {
          headers: { "X-Octop-Access-Token": "alice-renewed" },
        }),
      );
      await pending;
      expect(api.getAuthToken()).toBe("");
    },
  );

  it.each(transports)(
    "%s cannot overwrite another account with a renewal",
    async (transport) => {
      let respond!: (response: Response) => void;
      vi.stubGlobal(
        "fetch",
        vi.fn(
          () =>
            new Promise<Response>((resolve) => {
              respond = resolve;
            }),
        ),
      );
      const pending = api[transport]("/agents");
      api.setAuthToken("bob", false);
      respond(
        new Response("{}", {
          headers: { "X-Octop-Access-Token": "alice-renewed" },
        }),
      );
      await pending;
      expect(api.getAuthToken()).toBe("bob");
      expect(api.isSessionOnlyAuth()).toBe(true);
    },
  );

  it.each(transports)(
    "%s cannot log out another account after an old 401",
    async (transport) => {
      let respond!: (response: Response) => void;
      vi.stubGlobal(
        "fetch",
        vi.fn(
          () =>
            new Promise<Response>((resolve) => {
              respond = resolve;
            }),
        ),
      );
      const pending = api[transport]("/agents");
      api.setAuthToken("bob");
      respond(new Response("{}", { status: 401 }));
      await expect(pending).rejects.toThrow();
      expect(api.getAuthToken()).toBe("bob");
      expect(replace).not.toHaveBeenCalled();
    },
  );

  it("uploads cannot restore a previous session", async () => {
    const uploads: XMLHttpRequest[] = [];
    vi.spyOn(XMLHttpRequest.prototype, "send").mockImplementation(function (
      this: XMLHttpRequest,
    ) {
      uploads.push(this);
    });
    const pending = api.requestUpload("/uploads", new FormData());
    const upload = uploads[0];
    api.clearAuthToken();
    Object.defineProperty(upload, "status", { value: 200 });
    Object.defineProperty(upload, "responseText", { value: "{}" });
    vi.spyOn(upload, "getResponseHeader").mockReturnValue("alice-renewed");
    upload.dispatchEvent(new ProgressEvent("load"));
    await pending;
    expect(api.getAuthToken()).toBe("");
  });
});
