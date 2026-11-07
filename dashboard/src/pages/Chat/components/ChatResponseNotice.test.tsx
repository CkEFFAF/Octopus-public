import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ChatResponseNotice from "./ChatResponseNotice";
import type { ChatMessage } from "../hooks/useChat";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: { seconds?: number }) =>
      values?.seconds ? `${key}:${values.seconds}` : key,
  }),
}));
afterEach(() => vi.useRealTimers());
const message: ChatMessage = {
  id: "failed",
  role: "assistant",
  content: "HTTP 429",
  status: "error",
  timestamp: Date.now(),
};

it("uses the provider's cooldown and enables the original-answer action afterwards", () => {
  vi.useFakeTimers();
  vi.setSystemTime(100000);
  const retry = vi.fn();
  render(
    <ChatResponseNotice
      message={{
        ...message,
        timestamp: Date.now(),
        errorInfo: { diagnostic: { retry_after_seconds: 2 } },
      }}
      errorKey="HTTP 429"
      summary="limited"
      onRetry={retry}
    />,
  );
  const button = screen.getByRole("button", {
    name: "chat.recovery.retryIn:2",
  });
  expect(button).toBeDisabled();
  act(() => vi.advanceTimersByTime(2000));
  fireEvent.click(screen.getByRole("button", { name: "chat.retry" }));
  expect(retry).toHaveBeenCalledOnce();
});

it("deduplicates clicks while the original response is being recovered", async () => {
  let finish!: () => void;
  const retry = vi.fn(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  render(
    <ChatResponseNotice
      message={message}
      errorKey="HTTP 503"
      summary="busy"
      onRetry={retry}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "chat.retry" }));
  const button = screen.getByRole("button", { name: "chat.recovery.resuming" });
  expect(button).toBeDisabled();
  fireEvent.click(button);
  expect(retry).toHaveBeenCalledOnce();
  await act(async () => finish());
});

it("does not offer repeated retries for an exhausted quota returned as HTTP 429", () => {
  render(
    <ChatResponseNotice
      message={message}
      errorKey="HTTP 429 insufficient_quota"
      summary="Add credits"
      onRetry={vi.fn()}
    />,
  );
  expect(screen.queryByRole("button")).toBeNull();
  expect(screen.getByText("Add credits")).toBeInTheDocument();
  expect(screen.queryByText("chat.recovery.busyTitle")).toBeNull();
});
