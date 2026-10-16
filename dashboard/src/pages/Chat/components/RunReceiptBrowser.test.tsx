import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  executionApi,
  type RequestSnapshot,
  type RunEvent,
} from "../../../api/modules/execution";
import ContextRequestBrowser from "./ContextRequestBrowser";
import RunReceiptBrowser from "./RunReceiptBrowser";

vi.mock("../../../api/modules/execution", () => ({
  executionApi: { runs: vi.fn(), requests: vi.fn(), request: vi.fn() },
}));
const translation = vi.hoisted(() => ({ t: (key: string) => key }));
vi.mock("react-i18next", () => ({ useTranslation: () => translation }));
beforeEach(() => vi.clearAllMocks());

it("keeps the actual running receipt while an offline observation is unavailable", async () => {
  vi.mocked(executionApi.runs).mockResolvedValue({
    events: [
      {
        event_id: "job:context:training",
        seq: 1,
        run_id: "training-run",
        kind: "job",
        status: "running",
        context_id: "GPU-context",
        created_at: 1,
        updated_at: 20,
        payload: {
          job_id: "training",
          observed_at: 10,
          observation: { status: "unavailable", checked_at: 20 },
        },
      },
    ],
    has_more: false,
    next_before: null,
  });
  render(
    <RunReceiptBrowser
      agentId="expert"
      threadId="thread"
      onRequest={vi.fn()}
    />,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: /chat.runInspect.job/ }),
  );
  expect(
    await screen.findByText("chat.runInspect.observationUnavailable"),
  ).toBeInTheDocument();
  expect(screen.getByText("chat.runInspect.running")).toBeInTheDocument();
});

it("shows actual summarization separately from request deltas and retains removed component detail", async () => {
  const old = {
    request_id: "before",
    seq: 1,
    status: "completed",
    model: "model",
    composition: { user: 200 },
    estimated_input_tokens: 200,
    actual_usage: null,
    components: [
      {
        kind: "user",
        source_id: "u1",
        index: 0,
        estimated_tokens: 200,
        content: "Original retained context",
        sha256: "old",
        content_truncated: false,
      },
    ],
  } as RequestSnapshot;
  const current = {
    ...old,
    request_id: "after",
    seq: 2,
    estimated_input_tokens: 20,
    composition: { injected_context: 20 },
    transformation: {
      kind: "summarization",
      scope: "messages",
      before_estimated_tokens: 200,
      after_estimated_tokens: 20,
      before_message_count: 10,
      after_message_count: 2,
      summary_sha256: "summary",
      removed_source_ids: ["u1"],
      source_ids_truncated: false,
    },
    components: [
      {
        kind: "injected_context",
        source_type: "conversation_summary",
        index: 0,
        estimated_tokens: 20,
        content: "Summary of earlier context",
        sha256: "summary",
        content_truncated: false,
      },
    ],
  } as RequestSnapshot;
  vi.mocked(executionApi.requests).mockResolvedValue({
    requests: [current, old],
    has_more: false,
    next_before: null,
  });
  vi.mocked(executionApi.request).mockImplementation(
    async (_agent, _thread, id) => (id === "after" ? current : old),
  );
  render(<ContextRequestBrowser agentId="expert" threadId="thread" />);
  expect(
    await screen.findByText("chat.contextInspect.summarization"),
  ).toBeInTheDocument();
  // Components stay behind expand (S3 / 0020.1b detail card).
  fireEvent.click(screen.getByText("chat.contextInspect.expandComponents"));
  expect(
    await screen.findByText("chat.contextInspect.summarySource"),
  ).toBeInTheDocument();
  fireEvent.click(
    await screen.findByText("chat.contextInspect.removedComponents"),
  );
  expect(screen.getByText("Original retained context")).toBeInTheDocument();
  expect(screen.getByText("Summary of earlier context")).toBeInTheDocument();
});

it("shows unknown receipts and opens the request associated with that run", async () => {
  vi.mocked(executionApi.runs).mockResolvedValue({
    events: [
      {
        event_id: "operation",
        seq: 1,
        run_id: "actual-run",
        kind: "device",
        status: "unknown",
        context_id: "GPU-context",
        created_at: 1,
        updated_at: 2,
        payload: { action: "fs.write", device_id: "GPU", path: "/work/result" },
      },
      {
        event_id: "request",
        seq: 2,
        run_id: "actual-run",
        kind: "model",
        status: "completed",
        context_id: "GPU-context",
        created_at: 2,
        updated_at: 3,
        payload: { request_id: "exact-request" },
      },
    ] as RunEvent[],
    has_more: false,
    next_before: null,
  });
  const onRequest = vi.fn();
  render(
    <RunReceiptBrowser
      agentId="expert"
      threadId="thread"
      onRequest={onRequest}
    />,
  );
  expect(
    await screen.findByText("chat.runInspect.unknown"),
  ).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: /chat.runInspect.model/ }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "chat.runInspect.request" }),
  );
  expect(onRequest).toHaveBeenCalledWith("exact-request");
  expect(executionApi.runs).toHaveBeenCalledWith("expert", "thread", undefined);
});

it("inspects a correlated request even when it is older than the loaded request page", async () => {
  const recent = {
    request_id: "recent-request",
    seq: 100,
    model: "model",
    status: "completed",
    composition: {},
    estimated_input_tokens: 1,
  } as RequestSnapshot;
  vi.mocked(executionApi.requests).mockResolvedValue({
    requests: [recent],
    has_more: true,
    next_before: 100,
  });
  vi.mocked(executionApi.request).mockImplementation(
    async (_agent, _thread, id) => ({
      ...recent,
      request_id: id,
      seq: 1,
      components: [
        {
          kind: "user",
          index: 0,
          estimated_tokens: 10,
          content: "Retained exact request",
          content_truncated: false,
          sha256: "digest",
        },
      ],
      actual_usage: null,
    }),
  );
  render(
    <ContextRequestBrowser
      agentId="expert"
      threadId="thread"
      focusRequestId="old-request"
    />,
  );
  await waitFor(() =>
    expect(executionApi.request).toHaveBeenCalledWith(
      "expert",
      "thread",
      "old-request",
    ),
  );
  fireEvent.click(screen.getByText("chat.contextInspect.expandComponents"));
  expect(await screen.findByText("Retained exact request")).toBeInTheDocument();
  expect(executionApi.request).not.toHaveBeenCalledWith(
    "expert",
    "thread",
    "recent-request",
  );
});
