import { App } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { request } from "../../../../../api/request";
import type { ProviderRow } from "../../useProviders";
import { ProviderConfigModal } from "./ProviderConfigModal";

const { translate } = vi.hoisted(() => ({ translate: (key: string) => key }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: translate }) }));
vi.mock("../../../../../api/request", async (original) => ({
  ...(await original<typeof import("../../../../../api/request")>()),
  request: vi.fn().mockResolvedValue({}),
}));
vi.mock("./ModelListEditor", () => ({ ModelListEditor: () => null }));

const provider: ProviderRow = {
  id: 7,
  name: "Custom test",
  kind: "openai",
  base_url: "https://old.example/v1",
  api_key: null,
  note: "original",
  enabled: true,
  models: [{ id: "old-model", name: "Old model", enabled: true }],
};
beforeEach(() => vi.clearAllMocks());

it("preserves a draft during background refresh and patches only the user's edited fields", async () => {
  const onClose = vi.fn();
  const onSaved = vi.fn();
  const view = (row: ProviderRow, open = true) => (
    <App>
      <ProviderConfigModal
        provider={row}
        open={open}
        onClose={onClose}
        onSaved={onSaved}
      />
    </App>
  );
  const { rerender } = render(view(provider));
  const note = await screen.findByLabelText("models.noteLabel");
  await waitFor(() => expect(note).toHaveValue("original"));
  fireEvent.change(note, { target: { value: "my draft" } });
  const refreshed = {
    ...provider,
    base_url: "https://new.example/v1",
    note: "server note",
    models: [{ id: "new-model", name: "New model", enabled: true }],
  };
  rerender(view(refreshed));
  expect(note).toHaveValue("my draft");
  fireEvent.click(screen.getByRole("button", { name: "common.save" }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith(
      "/providers/7",
      expect.objectContaining({ method: "PATCH" }),
    ),
  );
  const patch = vi
    .mocked(request)
    .mock.calls.find(([, options]) => options?.method === "PATCH");
  expect(JSON.parse(patch?.[1]?.body as string)).toEqual({ note: "my draft" });
  rerender(view(refreshed, false));
  rerender(view(refreshed));
  await waitFor(() =>
    expect(screen.getByLabelText("models.noteLabel")).toHaveValue(
      "server note",
    ),
  );
  expect(screen.getByLabelText("Base URL")).toHaveValue(
    "https://new.example/v1",
  );
});

it("persists a chosen default by ordering it first in the model list", async () => {
  const second = { id: "second-model", name: "Second model", enabled: true };
  render(
    <App>
      <ProviderConfigModal
        provider={{ ...provider, models: [...provider.models, second] }}
        open
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />
    </App>,
  );
  const select = await screen.findByRole("combobox", {
    name: "models.defaultModelLabel",
  });
  fireEvent.mouseDown(select);
  fireEvent.click(await screen.findByText("Second model (second-model)"));
  fireEvent.click(screen.getByRole("button", { name: "common.save" }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith(
      "/providers/7",
      expect.objectContaining({ method: "PATCH" }),
    ),
  );
  const patch = vi
    .mocked(request)
    .mock.calls.find(([, options]) => options?.method === "PATCH");
  expect(JSON.parse(patch?.[1]?.body as string)).toEqual({
    models: [second, provider.models[0]],
  });
});

it("saves a typed default for a provider without any models", async () => {
  render(
    <App>
      <ProviderConfigModal
        provider={{ ...provider, models: [] }}
        open
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />
    </App>,
  );
  fireEvent.change(await screen.findByLabelText("models.defaultModelLabel"), {
    target: { value: "first-model" },
  });
  fireEvent.click(screen.getByRole("button", { name: "common.save" }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith(
      "/providers/7",
      expect.objectContaining({ method: "PATCH" }),
    ),
  );
  const patch = vi
    .mocked(request)
    .mock.calls.find(([, options]) => options?.method === "PATCH");
  expect(JSON.parse(patch?.[1]?.body as string)).toEqual({
    models: [{ id: "first-model", name: "first-model", enabled: true }],
  });
});
