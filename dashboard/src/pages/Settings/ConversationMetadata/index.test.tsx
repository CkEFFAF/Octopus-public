import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { conversationMetadataApi as api } from "../../../api/modules/conversationMetadata";
import Settings from "./index";

vi.mock("../../../context/AgentContext", () => ({
  useAgent: () => ({ agents: [] }),
}));
vi.mock("../../../api/modules/conversationMetadata", () => ({
  conversationMetadataApi: { settings: vi.fn(), saveSettings: vi.fn() },
}));

describe("account conversation models", () => {
  it("saves independent switches and the account revision without changing model choices", async () => {
    const settings = {
      revision: 3,
      title_enabled: true,
      brief_enabled: true,
      title_model: "p/title",
      brief_model: "same",
      models: [{ value: "p/title", label: "Title model" }],
      resolved_title_model: "p/title",
      resolved_brief_model: "p/title",
      title_available: true,
      brief_available: true,
    };
    vi.mocked(api.settings).mockResolvedValue(settings);
    vi.mocked(api.saveSettings).mockResolvedValue({
      ...settings,
      revision: 4,
      title_enabled: false,
    });
    render(
      <MemoryRouter>
        <App>
          <Settings />
        </App>
      </MemoryRouter>,
    );
    const title = await screen.findByRole("switch", {
      name: "conversationMetadata.autoTitle",
    });
    expect(title).toHaveAttribute("aria-checked", "true");
    fireEvent.click(title);
    expect(
      screen.getByRole("switch", { name: "conversationMetadata.autoBrief" }),
    ).toHaveAttribute("aria-checked", "true");
    fireEvent.click(screen.getByRole("button", { name: "common.save" }));
    await waitFor(() =>
      expect(api.saveSettings).toHaveBeenCalledWith({
        revision: 3,
        title_enabled: false,
        brief_enabled: true,
        title_model: "p/title",
        brief_model: "same",
      }),
    );
    expect(await screen.findByText("conversationMetadata.saved")).toBeTruthy();
  });
});
