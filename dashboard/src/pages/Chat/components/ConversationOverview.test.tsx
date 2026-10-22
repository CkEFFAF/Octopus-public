import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { App } from "antd";
import { describe, expect, it, vi } from "vitest";
import {
  conversationMetadataApi as api,
  type ConversationBrief,
} from "../../../api/modules/conversationMetadata";
import Overview from "./ConversationOverview";

vi.mock("./TaskActivity", () => ({
  OPEN_TASK_ACTIVITY_EVENT: "octop:open-task-activity",
}));
vi.mock("../../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "Asia/Shanghai",
}));
vi.mock("../../../hooks/useIsMobile", () => ({ useIsMobile: () => false }));
vi.mock("../../../api/modules/conversationMetadata", () => ({
  conversationMetadataApi: {
    brief: vi.fn(),
    source: vi.fn(),
    generate: vi.fn(),
    events: vi.fn(),
    digest: vi.fn(),
    job: vi.fn(),
    getDigest: vi.fn(),
  },
}));
const brief = (thread: string): ConversationBrief => ({
  thread_id: thread,
  revision: 1,
  objective_version: 1,
  title: `Title ${thread}`,
  title_source: "user",
  title_revision: 2,
  suggested_title: null,
  overview: {
    one_liner: "Current summary",
    objective: "Current goal",
    scope: "Scope",
    constraints: [],
  },
  progress: {
    stage: "Review",
    execution_state: "idle",
    work_state: "in_progress",
    display_state: "in_progress",
    observation: "current",
    completed: [],
    in_progress: [],
    remaining: [],
    blockers: [],
    next_actions: [
      { text: "Check evidence", source_refs: [{ kind: "message", id: "1" }] },
    ],
    reported_plan_completed: 1,
    plan_total: 2,
    verification_passed: 1,
    verification_reported: 2,
    verification: [
      {
        status: "passed",
        receipt_backed: true,
        source_refs: [{ kind: "run", id: "workflow:1" }],
      },
    ],
    acceptance: null,
  },
  decisions: [],
  findings: [],
  artifact_refs: [{ path: "/report.md", agent_id: "a" }],
  manual_overrides: {},
  provenance: {
    freshness: "current",
    generated_at: 100,
    effective_model_ref: "p/model",
    source_revision: 1,
    coverage: {
      message_seq: 1,
      message_offset: 0,
      archive_seq: 0,
      archive_offset: 0,
      event_seq: 0,
      complete: true,
      history_status: "ready",
      truncated_sources: false,
    },
    last_error: "",
  },
});

describe("conversation overview", () => {
  it("displays a ready digest even when reading the result completes after job polling", async () => {
    vi.mocked(api.brief).mockImplementation(async (_, thread) => brief(thread));
    vi.mocked(api.events).mockResolvedValue({
      events: [],
      next_cursor: null,
      from_ts: 1,
      to_ts: 2,
      timezone: "Asia/Shanghai",
      coverage: brief("t").provenance.coverage,
    });
    const pending = {
      job_id: "digest-job",
      kind: "digest",
      status: "queued",
      attempts: 0,
      error_code: "",
      result: {},
      updated_at: 1,
    };
    vi.mocked(api.digest).mockResolvedValue(pending);
    vi.mocked(api.job).mockResolvedValue({
      ...pending,
      status: "ready",
      result: { digest_id: "digest" },
    });
    let resolve: (
      value: Awaited<ReturnType<typeof api.getDigest>>,
    ) => void = () => {};
    vi.mocked(api.getDigest).mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    const { unmount } = render(
      <App>
        <Overview agentId="a" threadId="t" />
      </App>,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "conversationMetadata.overviewTitle",
      }),
    );
    await screen.findByText("Current goal");
    fireEvent.click(
      screen.getByRole("tab", { name: "conversationMetadata.timeline" }),
    );
    await screen.findByRole("button", {
      name: "conversationMetadata.generateDigest",
    });
    vi.useFakeTimers();
    try {
      await act(async () =>
        fireEvent.click(
          screen.getByRole("button", {
            name: "conversationMetadata.generateDigest",
          }),
        ),
      );
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
      expect(api.getDigest).toHaveBeenCalledWith("a", "t", "digest");
      await act(async () =>
        resolve({
          digest_id: "digest",
          window: "today",
          from_ts: 1,
          to_ts: 2,
          summary: "Visible period summary",
          event_ids: [],
          coverage: brief("t").provenance.coverage,
          source_revision: 1,
          generated_at: 1,
          effective_model_ref: "p/model",
          freshness: "current",
        }),
      );
      expect(screen.getByText("Visible period summary")).toBeTruthy();
    } finally {
      unmount();
      vi.useRealTimers();
    }
  });
  it("reads an attributed original and opens artifacts through the existing workspace", async () => {
    vi.mocked(api.brief).mockImplementation(async (_, thread) => brief(thread));
    vi.mocked(api.source).mockResolvedValue({
      kind: "message",
      id: "1",
      text: "Original user request",
      details: { role: "user" },
    });
    const openFile = vi.fn();
    render(
      <App>
        <Overview agentId="a" threadId="t" onOpenArtifact={openFile} />
      </App>,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "conversationMetadata.overviewTitle",
      }),
    );
    await screen.findByText("Current goal");
    fireEvent.click(
      screen.getAllByRole("button", { name: "conversationMetadata.source" })[0],
    );
    expect(await screen.findByText("Original user request")).toBeTruthy();
    expect(api.source).toHaveBeenCalledWith("a", "t", {
      kind: "message",
      id: "1",
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Close" }).at(-1)!);
    fireEvent.click(
      screen.getByRole("tab", {
        name: "conversationMetadata.decisionsAndResults",
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "/report.md" }));
    expect(openFile).toHaveBeenCalledWith("/report.md", "a");
  });
  it("discards a generation response after the user switches conversations", async () => {
    vi.mocked(api.brief).mockImplementation(async (_, thread) => brief(thread));
    let resolve: (
      value: Awaited<ReturnType<typeof api.generate>>,
    ) => void = () => {};
    vi.mocked(api.generate).mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    const { rerender } = render(
      <App>
        <Overview agentId="a" threadId="old" />
      </App>,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "conversationMetadata.overviewTitle",
      }),
    );
    await screen.findByText("Title old");
    fireEvent.click(
      screen.getByRole("button", { name: "conversationMetadata.regenerate" }),
    );
    await waitFor(() => expect(api.generate).toHaveBeenCalled());
    rerender(
      <App>
        <Overview agentId="a" threadId="new" />
      </App>,
    );
    await act(async () =>
      resolve({
        job_id: "old-job",
        kind: "brief",
        status: "queued",
        attempts: 0,
        error_code: "",
        result: {},
        updated_at: 1,
      }),
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "conversationMetadata.overviewTitle",
      }),
    );
    await screen.findByText("Title new");
    expect(screen.queryByText("conversationMetadata.generating")).toBeNull();
  });
});
