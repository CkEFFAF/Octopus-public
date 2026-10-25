import { beforeEach, expect, it, vi } from "vitest";

vi.mock("../../api/config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
}));
vi.mock("../../i18n", () => ({ default: { language: "zh" } }));

import { setAuthToken } from "../../api/request";
import { wizardApi, wizardSession } from "./wizardClient";

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  setAuthToken("unrelated-login");
  wizardSession.saveToken("verified-wizard-token");
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response('{"ok":true,"driver":"sqlite"}')),
  );
});

it.each(["testDatabase", "applyDatabase"] as const)(
  "%s authenticates with the verified wizard session",
  async (method) => {
    await wizardApi[method]({ driver: "sqlite", sqlite_path: "octop.db" });
    const options = vi.mocked(fetch).mock.calls[0][1];
    expect(new Headers(options?.headers).get("Authorization")).toBe(
      "Bearer verified-wizard-token",
    );
  },
);
