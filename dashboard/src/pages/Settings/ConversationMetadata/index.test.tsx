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
    organizationPage: vi.fn(),
    generate: vi.fn(),
  },
}));

describe("account conversation models", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.historyBatch).mockResolvedValue(null);
    vi.mocked(api.organizationPage).mockResolvedValue({
      items: [],
      total: 0,
      offset: 0,
      limit: 20,
    });
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
  it("confirms the filtered scope and sends the same age and failure conditions", async () => {
    vi.mocked(api.settings).mockResolvedValue(settings);
    vi.mocked(api.startHistoryBatch).mockResolvedValue(batch);
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
    fireEvent.mouseDown(
      screen.getByRole("combobox", { name: "organizationHistory.ageFilter" }),
    );
    fireEvent.click(await screen.findByText("organizationHistory.ages.older"));
    fireEvent.mouseDown(
      screen.getByRole("combobox", {
        name: "organizationHistory.statusFilter",
      }),
    );
    fireEvent.click(
      await screen.findByText("organizationHistory.status.failed"),
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "organizationHistory.organizeFiltered",
      }),
    );
    expect(
      screen.getByRole("radio", { name: "organizationHistory.filteredScope" }),
    ).toBeChecked();
    fireEvent.click(
      screen.getByRole("button", {
        name: "conversationMetadata.startOrganizing",
      }),
    );
    await waitFor(() =>
      expect(api.startHistoryBatch).toHaveBeenCalledWith({
        command_id: "batch-command",
        age_filter: "older",
        status_filter: "failed",
      }),
    );
  });
  it("automatically applies changes without Save or Cancel buttons", async () => {
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
    expect(screen.queryByRole("button", { name: "common.save" })).toBeNull();
    expect(screen.queryByRole("button", { name: "common.cancel" })).toBeNull();
    await waitFor(() =>
      expect(api.saveSettings).toHaveBeenCalledWith({
        revision: 3,
        title_enabled: false,
        brief_enabled: true,
        title_model: "p/title",
        brief_model: "same",
      }),
    );
    expect(
      await screen.findByText("conversationMetadata.applied"),
    ).toBeVisible();
  });
  it("serializes rapid edits using the confirmed revision and delays batch execution", async () => {
    vi.mocked(api.settings).mockResolvedValue(settings);
    let complete!: (value: typeof settings) => void;
    vi.mocked(api.saveSettings)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            complete = resolve;
          }),
      )
      .mockResolvedValueOnce({
        ...settings,
        revision: 5,
        title_enabled: false,
        brief_enabled: false,
      });
    render(
      <MemoryRouter>
        <App>
          <Settings />
        </App>
      </MemoryRouter>,
    );
    fireEvent.click(
      await screen.findByRole("switch", {
        name: "conversationMetadata.autoTitle",
      }),
    );
    fireEvent.click(
      screen.getByRole("switch", { name: "conversationMetadata.autoBrief" }),
    );
    expect(api.saveSettings).toHaveBeenCalledTimes(1);
    expect(screen.getByText("conversationMetadata.applying")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "conversationMetadata.organizeAll" }),
    ).toBeDisabled();
    complete({ ...settings, revision: 4, title_enabled: false });
    await waitFor(() =>
      expect(api.saveSettings).toHaveBeenNthCalledWith(2, {
        revision: 4,
        title_enabled: false,
        brief_enabled: false,
        title_model: "p/title",
        brief_model: "same",
      }),
    );
    await screen.findByText("conversationMetadata.applied");
    expect(
      screen.getByRole("switch", { name: "conversationMetadata.autoBrief" }),
    ).toHaveAttribute("aria-checked", "false");
  });
  it("restores confirmed settings and explains an automatic apply failure", async () => {
    vi.mocked(api.settings).mockResolvedValue(settings);
    vi.mocked(api.saveSettings).mockRejectedValueOnce(new Error("Unavailable"));
    render(
      <MemoryRouter>
        <App>
          <Settings />
        </App>
      </MemoryRouter>,
    );
    const toggle = await screen.findByRole("switch", {
      name: "conversationMetadata.autoTitle",
    });
    fireEvent.click(toggle);
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
    expect(
      screen.getAllByText("conversationMetadata.applyFailed").length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText("conversationMetadata.applied")).toBeNull();
  });
  it("opens historical batch failures even after the conversation has recovered", async () => {
    vi.mocked(api.settings).mockResolvedValue(settings);
    vi.mocked(api.historyBatch).mockResolvedValue({
      ...batch,
      total: 1,
      ready: 0,
      queued: 0,
      running: 0,
      failed: 1,
      recovered: 1,
      errors: { METADATA_INVALID_OUTPUT: 1 },
    });
    vi.mocked(api.organizationPage).mockImplementation(
      async (_a, _s, _o, batchId) => ({
        items: batchId
          ? [
              {
                thread_id: "recovered-thread",
                agent_id: "expert",
                agent_name: "Expert",
                title: "Recovered topic",
                status: "failed",
                latest_status: "ready",
                last_success_at: 200,
                last_attempt_at: 100,
                error_code: "METADATA_INVALID_OUTPUT",
                diagnostic: {},
                job_id: "old-job",
              },
            ]
          : [],
        total: batchId ? 1 : 0,
        offset: 0,
        limit: 20,
      }),
    );
    render(
      <MemoryRouter>
        <App>
          <Settings />
        </App>
      </MemoryRouter>,
    );
    await screen.findByText("organizationHistory.recoveredCount");
    expect(
      screen.queryByText("conversationMetadata.batchFailureHint"),
    ).toBeNull();
    fireEvent.click(
      screen.getByRole("button", {
        name: "organizationHistory.viewBatchFailures",
      }),
    );
    await waitFor(() =>
      expect(screen.getByText("Recovered topic")).toBeVisible(),
    );
    expect(api.organizationPage).toHaveBeenCalledWith(
      "all",
      "failed",
      0,
      "batch-command",
    );
    expect(
      screen.getByRole("button", { name: "organizationHistory.recovered" }),
    ).toBeDisabled();
  });
});
