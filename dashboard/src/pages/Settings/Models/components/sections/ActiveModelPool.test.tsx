import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ActiveModelPool } from "./ActiveModelPool";
import type { ProviderRow, ResolvedModel } from "../../useProviders";
import { request } from "../../../../../api/request";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("../../../../../api/request", () => ({ request: vi.fn() }));
vi.mock("@/utils/antdMessage", () => ({
  message: { success: vi.fn(), error: vi.fn() },
}));
const providers: ProviderRow[] = [
  {
    id: 1,
    name: "Local",
    kind: "openai",
    api_key: "synthetic",
    base_url: null,
    note: null,
    enabled: true,
    models: [],
  },
];
const models: ResolvedModel[] = ["fast-v1", "fast-v2"].map((model) => ({
  provider_id: 1,
  provider_name: "Local",
  provider_kind: "openai",
  model,
  name: "Fast",
  input: ["text"],
}));
function pool() {
  return render(
    <ActiveModelPool
      providers={providers}
      resolvedModels={models}
      activeModel={{ provider_name: "", model: "" }}
      modelReasoning={{}}
      onSaved={vi.fn()}
    />,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
});
describe("enabled model pool", () => {
  it("does not present a response for an older provider configuration as current verification", async () => {
    let finish!: (result: { ok: boolean }) => void;
    vi.mocked(request).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const view = pool();
    fireEvent.click(
      screen.getAllByRole("button", { name: /models.testConnection/ })[0],
    );
    view.rerender(
      <ActiveModelPool
        providers={[{ ...providers[0], base_url: "http://changed.invalid" }]}
        resolvedModels={models}
        activeModel={{ provider_name: "", model: "" }}
        modelReasoning={{}}
        onSaved={vi.fn()}
      />,
    );
    await act(async () => finish({ ok: true }));
    await waitFor(() =>
      expect(
        screen.getAllByRole("button", { name: /models.testConnection/ })[0],
      ).toBeEnabled(),
    );
    expect(screen.queryByText("uiFeedback.testPassed")).not.toBeInTheDocument();
    expect(screen.getAllByText("uiFeedback.notTested")).toHaveLength(2);
  });
  it("can recover from a search with no matches without changing the model", () => {
    pool();
    fireEvent.change(
      screen.getByRole("searchbox", { name: "uiFeedback.searchPool" }),
      { target: { value: "does-not-exist" } },
    );
    expect(screen.getByText("uiFeedback.noMatches")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "uiFeedback.clearSearch" }),
    );
    expect(screen.getByText("fast-v1")).toBeInTheDocument();
    expect(screen.getByText("fast-v2")).toBeInTheDocument();
    expect(request).not.toHaveBeenCalled();
  });
  it("distinguishes duplicate display names by ID and filters by ID", () => {
    pool();
    expect(screen.getByText("fast-v1")).toBeInTheDocument();
    expect(screen.getByText("fast-v2")).toBeInTheDocument();
    fireEvent.change(
      screen.getByRole("searchbox", { name: "uiFeedback.searchPool" }),
      { target: { value: "v2" } },
    );
    expect(screen.queryByText("fast-v1")).not.toBeInTheDocument();
    expect(screen.getByText("fast-v2")).toBeInTheDocument();
    expect(request).not.toHaveBeenCalled();
  });
  it("does not imply verification or call a model before an explicit test", async () => {
    vi.mocked(request).mockResolvedValue({
      ok: false,
      error: "local unavailable",
    });
    pool();
    expect(screen.getAllByText("uiFeedback.notTested")).toHaveLength(2);
    expect(request).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getAllByRole("button", { name: /models.testConnection/ })[0],
    );
    await waitFor(() =>
      expect(
        screen.getByText("uiFeedback.testFailedStatus"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getAllByRole("button", { name: /models.testConnection/ }),
    ).toHaveLength(2);
  });
});
