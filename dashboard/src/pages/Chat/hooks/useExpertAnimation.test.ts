import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useExpertAnimation } from "./useExpertAnimation";
import type { ChatMessage } from "./sseHelpers";
afterEach(() => vi.useRealTimers());
const messages: ChatMessage[] = [
  { id: "u", role: "user", content: "hello", timestamp: 1 },
];
describe("expert completion and pause", () => {
  it("celebrates only a live completion and expires across session navigation", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(
      (props) => useExpertAnimation({ messages, state: "running", ...props }),
      { initialProps: { running: false, sessionKey: "a" } },
    );
    expect(result.current.phase).toBe("idle");
    rerender({ running: true, sessionKey: "a" });
    rerender({ running: false, sessionKey: "a" });
    expect(result.current.phase).toBe("success");
    rerender({ running: false, sessionKey: "b" });
    act(() => vi.advanceTimersByTime(2300));
    rerender({ running: false, sessionKey: "a" });
    expect(result.current.phase).toBe("idle");
  });
  it("shows pause after cancellation and clears it when resumed", () => {
    const { result, rerender } = renderHook(
      (props) =>
        useExpertAnimation({
          messages,
          state: "running",
          sessionKey: "a",
          ...props,
        }),
      { initialProps: { running: true } },
    );
    act(() => result.current.pause());
    rerender({ running: false });
    expect(result.current.phase).toBe("paused");
    rerender({ running: true });
    expect(result.current.phase).toBe("thinking");
  });
});
