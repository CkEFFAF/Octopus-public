import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { describe, expect, it, vi } from "vitest";
import { request } from "../../../../api/request";
import { fetchProviderModels } from "../providerApi";
import FreeModelChannels from "./FreeModelChannels";

vi.mock("../../../../api/request", () => ({ request: vi.fn() }));
vi.mock("../providerApi", () => ({ fetchProviderModels: vi.fn() }));
describe("free model channels", () => {
  it("explicitly enables the entire discovered free roster without losing model settings", async () => {
    vi.mocked(request).mockResolvedValue({ items: [] });
    vi.mocked(fetchProviderModels).mockResolvedValue({
      ok: true,
      models: [
        { id: "first", name: "First" },
        { id: "new", name: "New" },
      ],
    });
    const onSaved = vi.fn().mockResolvedValue(undefined);
    render(
      <App>
        <FreeModelChannels
          providers={[
            {
              id: 7,
              name: "Our Free Model",
              kind: "openai",
              api_key: "fictional-key",
              base_url: "http://127.0.0.1:18900/v1",
              enabled: true,
              note: null,
              models: [
                {
                  id: "first",
                  name: "First",
                  enabled: false,
                  max_output_tokens: 3200,
                },
              ],
            },
          ]}
          onSaved={onSaved}
        />
      </App>,
    );
    fireEvent.click(screen.getByRole("button", { name: "models.syncAllFree" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
    const call = vi
      .mocked(request)
      .mock.calls.find((args) => args[0] === "/providers/7");
    const body = JSON.parse(call![1]!.body as string);
    expect(body.models).toHaveLength(2);
    expect(
      body.models.every((model: { enabled: boolean }) => model.enabled),
    ).toBe(true);
    expect(body.models[0].max_output_tokens).toBe(3200);
    expect(
      vi
        .mocked(request)
        .mock.calls.some((args) => (args[0] as string).startsWith("https://")),
    ).toBe(false);
  });
});
