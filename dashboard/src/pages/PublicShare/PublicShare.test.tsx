import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import PublicSharePage from "./index";
import App from "../../App";

const privateMount = vi.hoisted(() =>
  vi.fn(() => {
    throw new Error("Private shell must not mount");
  }),
);
vi.mock("../../components/AuthGuard", () => ({ default: privateMount }));
vi.mock("../../layouts/MainLayout", () => ({ default: privateMount }));
vi.mock("../../pages/Login", () => ({ default: () => null }));
vi.mock("../../pages/Login/OidcComplete", () => ({ default: () => null }));
vi.mock("../../pages/Setup", () => ({ default: () => null }));
vi.mock("../../pages/Invite", () => ({ default: () => null }));
vi.mock("../../api/config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
}));
const token = "A".repeat(43);
const snapshot = {
  title: "Synthetic public snapshot",
  timezone: "Asia/Shanghai",
  created_at: 1792285200,
  expires_at: null,
  messages: [
    { id: 1, role: "user", content: "Reviewed public text" },
    { id: 2, role: "assistant", content: "Public result" },
  ],
};
let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  privateMount.mockClear();
  fetchMock = vi
    .fn()
    .mockResolvedValue({ ok: true, json: async () => snapshot });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

function renderPublic(value = token) {
  return render(
    <MemoryRouter initialEntries={[`/share/${value}`]}>
      <Routes>
        <Route path="/share/:token" element={<PublicSharePage />} />
      </Routes>
    </MemoryRouter>,
  );
}

it("opens the real top-level route without login/private providers and fetches without credentials or cache", async () => {
  localStorage.setItem("auth_token", "SYNTHETIC_AUTH_MUST_NOT_SEND");
  window.history.replaceState(null, "", `/share/${token}`);
  const view = render(<App />);
  expect(await screen.findByText("Reviewed public text")).toBeInTheDocument();
  expect(privateMount).not.toHaveBeenCalled();
  const [, options] = fetchMock.mock.calls[0];
  expect(fetchMock.mock.calls[0][0]).toBe(`/api/public/thread-shares/${token}`);
  expect(options).toMatchObject({
    method: "GET",
    credentials: "omit",
    cache: "no-store",
    referrerPolicy: "no-referrer",
    redirect: "error",
    headers: { Accept: "application/json" },
  });
  expect(options.headers.Authorization).toBeUndefined();
  expect(document.head.querySelector('meta[name="robots"]')).toHaveAttribute(
    "content",
    "noindex, nofollow, noarchive",
  );
  expect(document.head.querySelector('meta[name="referrer"]')).toHaveAttribute(
    "content",
    "no-referrer",
  );
  view.unmount();
  expect(
    document.head.querySelector('meta[name="robots"]'),
  ).not.toBeInTheDocument();
  localStorage.removeItem("auth_token");
});

it("clears the snapshot on focus after revoke without redirecting to login or storing content", async () => {
  renderPublic();
  await screen.findByText("Public result");
  fetchMock.mockResolvedValue({ ok: false, status: 404 });
  fireEvent(window, new Event("focus"));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "chatShare.unavailable",
  );
  expect(screen.queryByText("Reviewed public text")).not.toBeInTheDocument();
  expect(screen.queryByText(snapshot.title)).not.toBeInTheDocument();
  expect(privateMount).not.toHaveBeenCalled();
  expect(Object.values(localStorage)).not.toContain(JSON.stringify(snapshot));
});

it("revalidates every 30 seconds only while visible and clears retained content on network failure, then retries online", async () => {
  vi.useFakeTimers();
  renderPublic();
  await act(async () => {});
  expect(screen.getByText("Reviewed public text")).toBeInTheDocument();
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: "hidden",
  });
  await act(async () => {
    vi.advanceTimersByTime(30000);
  });
  expect(fetchMock).toHaveBeenCalledTimes(1);
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: "visible",
  });
  fetchMock.mockRejectedValueOnce(
    new TypeError("Network failed: secret transport detail"),
  );
  await act(async () => {
    vi.advanceTimersByTime(30000);
  });
  expect(screen.getByRole("alert")).toHaveTextContent("chatShare.unavailable");
  expect(screen.queryByText("Reviewed public text")).not.toBeInTheDocument();
  expect(screen.queryByText(/secret transport/)).not.toBeInTheDocument();
  await act(async () => {
    window.dispatchEvent(new Event("online"));
  });
  expect(screen.getByText("Reviewed public text")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(3);
});

it("shows the same unavailable state for malformed capabilities without performing any lookup", async () => {
  renderPublic("not-a-token");
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "chatShare.unavailable",
  );
  expect(fetchMock).not.toHaveBeenCalled();
});
