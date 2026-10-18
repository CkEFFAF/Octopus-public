import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import {
  collaborationApi,
  downloadCollaborationResource,
  type CollaborationInvocation,
  type CollaborationResource,
  type CollaborationPage,
} from "../../../api/modules/collaboration";
import CollaborationPanel from "./CollaborationPanel";
import en from "../../../locales/en.json";
import zh from "../../../locales/zh.json";

vi.mock("../../../api/modules/collaboration", () => ({
  collaborationApi: { list: vi.fn(), detail: vi.fn() },
  downloadCollaborationResource: vi.fn(),
}));
vi.mock("../../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "Asia/Shanghai",
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const invocation: CollaborationInvocation = {
  invocation_id: "attempt-1",
  source_agent_id: "parent",
  callee_agent_id: "scientist",
  source_thread_id: "parent-chat",
  child_thread_id: "child-chat-1",
  root_run_id: "run",
  parent_invocation_id: null,
  retry_of: null,
  transport_status: "completed",
  task_outcome: "unknown",
  target_policy: "member_default",
  requested_target: {},
  resolved_target: {
    device_id: "gpu-1",
    device_name: "Lab GPU",
    target_kind: "device",
  },
  error_code: null,
  retryable: false,
  prompt: "Review the paper",
  created_at: 1792285200,
  updated_at: 1792285260,
};
const resource: CollaborationResource = {
  resource_id: "report-1",
  version: "a".repeat(64),
  name: "Report.pdf",
  media_type: "application/pdf",
  size: 42,
  source_agent_id: "scientist",
  source_thread_id: "child-chat-1",
  source_kind: "device",
  source_device_id: "gpu-1",
  parse_state: "ready",
  publication_state: "published",
  delivery_status: "completed",
  content_url: "/api/content",
  download_url: "/api/content?download=true",
  created_at: 1792285260,
};
const snapshot = (
  changes: Partial<CollaborationPage> = {},
): CollaborationPage => ({
  invocations: [invocation],
  artifacts: [resource],
  events: [
    {
      event_id: "accepted",
      event_type: "delegation.accepted",
      seq: 1,
      invocation_id: "attempt-1",
      resource_id: null,
      payload: { private: "NEVER RENDER INTERNAL PAYLOAD" },
      created_at: invocation.created_at,
    },
  ],
  next_cursor: 1,
  has_more: false,
  ...changes,
});
beforeEach(() => vi.clearAllMocks());

it("opens the parent collaboration entry, pages public work, refreshes without copies, previews/downloads and navigates to its child", async () => {
  vi.mocked(collaborationApi.list).mockResolvedValue(snapshot());
  vi.mocked(collaborationApi.detail)
    .mockResolvedValueOnce({
      invocation,
      messages: [
        {
          seq: 2,
          role: "assistant",
          content: [
            { type: "reasoning", text: "PRIVATE REASONING" },
            {
              type: "text",
              text: "Report ready. <think>PRIVATE THOUGHT</think>",
            },
          ],
          created_at: invocation.updated_at,
        },
        {
          seq: 3,
          role: "system",
          content: "PRIVATE SYSTEM",
          created_at: invocation.updated_at,
        },
      ],
      has_more: true,
      next_before: 2,
    })
    .mockResolvedValueOnce({
      invocation,
      messages: [
        {
          seq: 1,
          role: "user",
          content: "Review the methods",
          created_at: invocation.created_at,
        },
        {
          seq: 2,
          role: "assistant",
          content: "Report ready.",
          created_at: invocation.updated_at,
        },
      ],
      has_more: false,
      next_before: null,
    });
  const preview = vi.fn();
  render(
    <MemoryRouter initialEntries={["/chat/parent/parent-chat"]}>
      <Routes>
        <Route
          path="/chat/parent/parent-chat"
          element={
            <CollaborationPanel
              agentId="parent"
              threadId="parent-chat"
              agentNameById={{ scientist: "Paper expert" }}
              onOpenResource={preview}
            />
          }
        />
        <Route
          path="/chat/scientist/child-chat-1"
          element={<p>Child conversation</p>}
        />
      </Routes>
    </MemoryRouter>,
  );
  await waitFor(() =>
    expect(collaborationApi.list).toHaveBeenCalledWith(
      "parent",
      "parent-chat",
      0,
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: /collaboration.title/ }));
  fireEvent.click(
    await screen.findByRole("button", { name: /Paper expert.*Lab GPU/ }),
  );
  expect(await screen.findByText("Report ready.")).toBeInTheDocument();
  expect(screen.queryByText(/PRIVATE/)).not.toBeInTheDocument();
  expect(
    screen.queryByText("collaboration.outcomeStatus.succeeded"),
  ).not.toBeInTheDocument();
  expect(
    screen.getByText(/collaboration.outcomeStatus.unknown/),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "collaboration.older" }));
  expect(await screen.findByText("Review the methods")).toBeInTheDocument();
  expect(collaborationApi.detail).toHaveBeenLastCalledWith(
    "parent",
    "parent-chat",
    "attempt-1",
    2,
  );
  expect(screen.getAllByText("Report ready.")).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "common.preview" }));
  expect(preview).toHaveBeenCalledWith(resource);
  fireEvent.click(screen.getByRole("button", { name: "common.download" }));
  await waitFor(() =>
    expect(downloadCollaborationResource).toHaveBeenCalledWith(
      "parent",
      "parent-chat",
      resource,
    ),
  );
  fireEvent.click(screen.getAllByRole("button", { name: "common.refresh" })[0]);
  await waitFor(() =>
    expect(collaborationApi.list).toHaveBeenLastCalledWith(
      "parent",
      "parent-chat",
      1,
    ),
  );
  expect(
    screen.getAllByRole("button", { name: /Paper expert.*Lab GPU/ }),
  ).toHaveLength(1);
  expect(screen.getAllByText("Report.pdf")).toHaveLength(1);
  expect(
    screen.getByText("collaboration.delivery.completed"),
  ).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("link", { name: "collaboration.openChild" }),
  );
  expect(await screen.findByText("Child conversation")).toBeInTheDocument();
});

it("recovers missed updates, retains attempts and uses the current delivery snapshot over older replay events", async () => {
  vi.mocked(collaborationApi.list)
    .mockResolvedValueOnce(snapshot())
    .mockResolvedValue(
      snapshot({
        invocations: [
          invocation,
          {
            ...invocation,
            invocation_id: "attempt-2",
            child_thread_id: "child-chat-2",
            retry_of: "attempt-1",
            transport_status: "unknown",
            task_outcome: "blocked",
            resolved_target: null,
          },
        ],
        artifacts: [
          {
            ...resource,
            publication_state: "revoked",
            delivery_status: "failed",
          },
        ],
        events: [
          {
            seq: 2,
            event_id: "earlier-delivery",
            event_type: "resource.delivered",
            resource_id: "report-1",
            invocation_id: null,
            payload: { error_code: "checksum_mismatch" },
            created_at: invocation.updated_at,
          },
        ],
        next_cursor: 2,
      }),
    );
  render(
    <MemoryRouter>
      <CollaborationPanel
        agentId="parent"
        threadId="parent-chat"
        onOpenResource={vi.fn()}
      />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByRole("button", { name: /collaboration.title/ }));
  await screen.findByText("Report.pdf");
  fireEvent(window, new Event("online"));
  expect(
    await screen.findByText("collaboration.delivery.failed"),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "common.preview" })).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "common.download" }),
  ).toBeDisabled();
  expect(
    screen.getAllByRole("button", {
      name: /scientist.*collaboration.transport/,
    }),
  ).toHaveLength(2);
  expect(
    screen.getByText(/collaboration.outcomeStatus.blocked/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/collaboration.unresolved/, { selector: "span" }),
  ).toBeInTheDocument();
});

it("exposes loading, failed GET, retry and empty states without dispatching work", async () => {
  let resolve!: (page: CollaborationPage) => void;
  vi.mocked(collaborationApi.list)
    .mockRejectedValueOnce(new Error("secret host path must not leak"))
    .mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
  render(
    <MemoryRouter>
      <CollaborationPanel
        agentId="parent"
        threadId="parent-chat"
        onOpenResource={vi.fn()}
      />
    </MemoryRouter>,
  );
  expect(screen.getByRole("status")).toHaveTextContent("collaboration.loading");
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "collaboration.loadError",
  );
  expect(screen.queryByText(/secret host/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "common.refresh" }));
  await waitFor(() => expect(collaborationApi.list).toHaveBeenCalledTimes(2));
  resolve(
    snapshot({ invocations: [], artifacts: [], events: [], next_cursor: 0 }),
  );
  fireEvent.click(screen.getByRole("button", { name: /collaboration.title/ }));
  expect(await screen.findByText("collaboration.empty")).toBeInTheDocument();
  expect(
    within(screen.getByRole("region")).queryByRole("alert"),
  ).not.toBeInTheDocument();
});

it.each([
  ["COLLABORATION_RESTART_UNCONFIRMED", "unknown", "restartUnconfirmed"],
  ["PEER_CANCEL_REQUESTED", "running", "cancelRequested"],
  ["PEER_RECEIPT_PERSISTENCE_FAILED", "unknown", "receiptPersistenceFailed"],
  ["SECRET C:/private/account/token", "unknown", "unknown"],
  ["__proto__", "unknown", "unknown"],
] as const)(
  "shows bounded reason for %s without classifying uncertain work as failed",
  async (code, status, reason) => {
    vi.mocked(collaborationApi.list).mockResolvedValue(
      snapshot({
        invocations: [
          {
            ...invocation,
            transport_status: status,
            task_outcome: "unknown",
            error_code: code,
          },
        ],
        artifacts: [],
      }),
    );
    render(
      <MemoryRouter>
        <CollaborationPanel
          agentId="parent"
          threadId="parent-chat"
          onOpenResource={vi.fn()}
        />
      </MemoryRouter>,
    );
    fireEvent.click(
      screen.getByRole("button", { name: /collaboration.title/ }),
    );
    expect(
      await screen.findByText(`collaboration.reasons.${reason}`),
    ).toBeInTheDocument();
    expect(
      screen.getByText(`collaboration.reasons.${reason}`).closest("[role]"),
    ).toHaveAttribute("role", "status");
    expect(
      screen.getByText(new RegExp(`collaboration.status.${status}`)),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        /operationFailed|collaboration.status.failed|collaboration.outcomeStatus.failed/,
      ),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(code)).not.toBeInTheDocument();
  },
);

it("refreshes a ready report to unavailable, disables actions and explains the missing snapshot", async () => {
  const unavailable = {
    ...resource,
    publication_state: "unavailable",
    error_code: "RESOURCE_SNAPSHOT_UNAVAILABLE",
  };
  vi.mocked(collaborationApi.list)
    .mockResolvedValueOnce(snapshot())
    .mockResolvedValue(
      snapshot({
        artifacts: [unavailable],
        events: [
          {
            seq: 2,
            event_id: "snapshot-missing",
            event_type: "resource.unavailable",
            invocation_id: "attempt-1",
            resource_id: resource.resource_id,
            payload: {
              error_code: "RESOURCE_SNAPSHOT_UNAVAILABLE",
              message: "C:/SECRET/snapshots/report",
            },
            created_at: invocation.updated_at,
          },
        ],
        next_cursor: 2,
      }),
    );
  vi.mocked(collaborationApi.detail).mockResolvedValue({
    invocation,
    messages: [],
    has_more: false,
    next_before: null,
  });
  render(
    <MemoryRouter>
      <CollaborationPanel
        agentId="parent"
        threadId="parent-chat"
        onOpenResource={vi.fn()}
      />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByRole("button", { name: /collaboration.title/ }));
  expect(
    await screen.findByRole("button", { name: "common.preview" }),
  ).toBeEnabled();
  expect(screen.getByRole("button", { name: "common.download" })).toBeEnabled();
  fireEvent(window, new Event("online"));
  expect(
    await screen.findByText("collaboration.reasons.snapshotUnavailable"),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "common.preview" })).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "common.download" }),
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: /scientist.*Lab GPU/ }));
  expect(
    await screen.findByText(/collaboration.events.resource_unavailable/),
  ).toBeInTheDocument();
  expect(
    screen.queryByText(/SECRET|RESOURCE_SNAPSHOT_UNAVAILABLE/),
  ).not.toBeInTheDocument();
});

it("retains a late cancellation event without changing completed task status", async () => {
  vi.mocked(collaborationApi.list).mockResolvedValue(
    snapshot({
      events: [
        {
          seq: 2,
          event_id: "late-cancel",
          event_type: "delegation.cancel_too_late",
          invocation_id: invocation.invocation_id,
          resource_id: null,
          payload: {},
          created_at: invocation.updated_at,
        },
      ],
    }),
  );
  vi.mocked(collaborationApi.detail).mockResolvedValue({
    invocation,
    messages: [],
    has_more: false,
    next_before: null,
  });
  render(
    <MemoryRouter>
      <CollaborationPanel
        agentId="parent"
        threadId="parent-chat"
        onOpenResource={vi.fn()}
      />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByRole("button", { name: /collaboration.title/ }));
  fireEvent.click(
    await screen.findByRole("button", { name: /scientist.*Lab GPU/ }),
  );
  expect(
    await screen.findByText(/collaboration.events.delegation_cancel_too_late/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/collaboration.status.completed/),
  ).toBeInTheDocument();
});

it("keeps collaboration reasons and events bilingual with the canonical tool labels intact", () => {
  expect(Object.keys(en.collaboration.reasons).sort()).toEqual(
    Object.keys(zh.collaboration.reasons).sort(),
  );
  expect(Object.keys(en.collaboration.events).sort()).toEqual(
    Object.keys(zh.collaboration.events).sort(),
  );
  expect(en.collaboration.reasons.cancelRequested).toContain(
    "not yet been confirmed",
  );
  expect(zh.collaboration.reasons.cancelRequested).toContain("尚未确认");
  expect(en.collaboration.reasons.restartUnconfirmed).not.toMatch(/failed/i);
  expect(zh.collaboration.reasons.restartUnconfirmed).not.toContain("失败");
  expect(en.tools.read_attachment).toBe("Read attachment");
  expect(zh.tools.read_attachment).toBe("读取附件");
});
