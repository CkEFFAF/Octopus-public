import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { conversationMetadataApi as api } from "../../../api/modules/conversationMetadata";
import Settings from "./index";

vi.mock("../../../context/AgentContext", () => ({
  useAgent: () => ({ agents: [] }),
}));
vi.mock("../../../api/modules/conversationMetadata", () => ({
  metadataCommandId: () => "batch-command",
  conversationMetadataApi: {
    settings: vi.fn(),
    saveSettings: vi.fn(),
    historyBatch: vi.fn(),
    startHistoryBatch: vi.fn(),
    cancelHistoryBatch: vi.fn(),
  },
}));

describe("account conversation models", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.historyBatch).mockResolvedValue(null);
  });
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
  const batch = {
    batch_id: "batch-command",
    total: 83,
    queued: 82,
    running: 1,
    ready: 0,
    failed: 0,
    cancelled: 0,
  };
  it("stops the restored active batch and displays safe diagnostic details", async () => {
    vi.mocked(api.settings).mockResolvedValue(settings);
    vi.mocked(api.historyBatch).mockResolvedValue({
      ...batch,
      failed: 2,
      errors: { METADATA_INVALID_OUTPUT: 2 },
      failures: [
        {
          job_id: "failed-job",
          thread_id: "thread",
          code: "METADATA_INVALID_OUTPUT",
          diagnostic: {
            issues: [{ path: "remaining.0.source_refs", type: "missing" }],
          },
        },
        {
          job_id: "another-job",
          thread_id: "another-thread",
          code: "METADATA_INVALID_OUTPUT",
          diagnostic: {},
        },
      ],
    });
    vi.mocked(api.cancelHistoryBatch).mockImplementation(async () => {
      const cancelled = { ...batch, queued: 0, running: 0, cancelled: 83 };
      vi.mocked(api.historyBatch).mockResolvedValue(cancelled);
      return cancelled;
    });
    render(
      <MemoryRouter>
        <App>
          <Settings />
        </App>
      </MemoryRouter>,
    );
    const stop = await screen.findByRole("button", {
      name: "conversationMetadata.stopOrganizing",
    });
    expect(screen.queryByText(/remaining.0.source_refs/)).toBeNull();
    const details = screen.getAllByRole("button", {
      name: "common.failureDetails",
    });
    expect(details).toHaveLength(1);
    fireEvent.click(details[0]);
    await waitFor(() =>
      expect(screen.getByText(/remaining.0.source_refs/)).toBeVisible(),
    );
    fireEvent.click(screen.getByRole("button", { name: "common.close" }));
    fireEvent.click(stop);

    await waitFor(() =>
      expect(api.cancelHistoryBatch).toHaveBeenCalledWith("batch-command"),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("button", {
          name: "conversationMetadata.stopOrganizing",
        }),
      ).toBeNull(),
    );
  });
  it("starts all history by default without choosing an Agent or conversation", async () => {
    vi.mocked(api.settings).mockResolvedValue(settings);
    vi.mocked(api.startHistoryBatch).mockImplementation(async () => {
      vi.mocked(api.historyBatch).mockResolvedValue(batch);
      return batch;
    });
    render(
      <MemoryRouter>
        <App>
          <Settings />
        </App>
      </MemoryRouter>,
    );
    await screen.findByRole("switch", {
      name: "conversationMetadata.autoTitle",
    });
    fireEvent.click(
      screen.getByRole("button", { name: "conversationMetadata.organizeAll" }),
    );
    expect(
      screen.getByRole("radio", { name: "conversationMetadata.allHistory" }),
    ).toBeChecked();
    expect(
      screen.queryByRole("combobox", { name: "conversationMetadata.agent" }),
    ).toBeNull();
    const start = screen.getByRole("button", {
      name: "conversationMetadata.startOrganizing",
    });
    expect(start).toBeEnabled();
    fireEvent.click(start);
    await waitFor(() =>
      expect(api.startHistoryBatch).toHaveBeenCalledWith({
        command_id: "batch-command",
      }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "conversationMetadata.batchProgress",
    );
    expect(
      screen.getByRole("button", {
        name: "conversationMetadata.batchInProgress",
      }),
    ).toBeDisabled();
  });
  it("restores the durable batch after reopening settings", async () => {
    vi.mocked(api.settings).mockResolvedValue(settings);
    vi.mocked(api.historyBatch).mockResolvedValue(batch);
    render(
      <MemoryRouter>
        <App>
          <Settings />
        </App>
      </MemoryRouter>,
    );
    expect(await screen.findByRole("status")).toBeVisible();
    expect(
      screen.getByRole("button", {
        name: "conversationMetadata.batchInProgress",
      }),
    ).toBeDisabled();
    expect(api.startHistoryBatch).not.toHaveBeenCalled();
  });
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
