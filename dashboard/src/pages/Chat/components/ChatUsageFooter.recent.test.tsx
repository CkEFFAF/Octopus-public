import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useRecentRequestUsage } from "../hooks/useRecentRequestUsage";
import ChatUsageFooter from "./ChatUsageFooter";
vi.mock("../hooks/useRecentRequestUsage", () => ({
  useRecentRequestUsage: vi.fn(),
}));
const messages = [
  {
    id: "legacy",
    role: "assistant" as const,
    content: "done",
    timestamp: 1,
    usage: {
      input_tokens: 1000000,
      cache_read_tokens: 0,
      output_tokens: 100,
      total_tokens: 1000100,
    },
  },
];
it("shows current request cache instead of a legacy conversation's cumulative zero", () => {
  vi.mocked(useRecentRequestUsage).mockReturnValue({
    entry: {
      actual_usage: {
        input_tokens: 243320,
        cache_read_tokens: 239232,
        cache_metrics_reported: true,
      },
    } as never,
    failed: false,
    loading: false,
  });
  render(
    <ChatUsageFooter
      messages={messages}
      hasMore
      loading={false}
      agentId="a"
      threadId="t"
      isStreaming
    />,
  );
  expect(screen.getByTestId("chat-usage-summary")).toHaveTextContent(
    "chatUsage.recentCacheHit 98.3%",
  );
  expect(screen.getByTestId("chat-usage-summary")).not.toHaveTextContent(" 0%");
  expect(useRecentRequestUsage).toHaveBeenCalledWith("a", "t", true);
});
it("distinguishes pending, unreported and an explicitly reported cold zero", () => {
  vi.mocked(useRecentRequestUsage).mockReturnValue({
    entry: null,
    failed: false,
    loading: true,
  });
  const view = render(
    <ChatUsageFooter
      messages={messages}
      hasMore
      loading={false}
      agentId="a"
      threadId="t"
      isStreaming
    />,
  );
  expect(screen.getByTestId("chat-usage-summary")).toHaveTextContent(
    "chatUsage.cachePending",
  );
  expect(screen.getByTestId("chat-usage-summary")).not.toHaveTextContent("%");
  vi.mocked(useRecentRequestUsage).mockReturnValue({
    entry: {
      actual_usage: { input_tokens: 100, cache_metrics_reported: false },
    } as never,
    failed: false,
    loading: false,
  });
  view.rerender(
    <ChatUsageFooter
      messages={messages}
      hasMore
      loading={false}
      agentId="a"
      threadId="t"
    />,
  );
  expect(screen.getByTestId("chat-usage-summary")).toHaveTextContent(
    "chatUsage.cacheUnavailable",
  );
  vi.mocked(useRecentRequestUsage).mockReturnValue({
    entry: {
      actual_usage: {
        input_tokens: 100,
        cache_read_tokens: 0,
        cache_metrics_reported: true,
      },
    } as never,
    failed: false,
    loading: false,
  });
  view.rerender(
    <ChatUsageFooter
      messages={messages}
      hasMore
      loading={false}
      agentId="a"
      threadId="t"
    />,
  );
  expect(screen.getByTestId("chat-usage-summary")).toHaveTextContent(
    "chatUsage.recentCacheHit 0%",
  );
});
