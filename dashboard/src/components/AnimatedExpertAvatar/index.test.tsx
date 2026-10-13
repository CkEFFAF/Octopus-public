import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AnimatedExpertAvatar from ".";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});
describe("animated expert playback", () => {
  it("advances pose frames and resets immediately for approval and error", () => {
    vi.useFakeTimers();
    const { container, rerender } = render(
      <AnimatedExpertAvatar species="fox" phase="coding" />,
    );
    const frame = () =>
      container.querySelector("[data-frame]")?.getAttribute("data-frame");
    expect(frame()).toBe("14");
    act(() => vi.advanceTimersByTime(750));
    expect(frame()).toBe("15");
    rerender(<AnimatedExpertAvatar species="fox" phase="waiting_permission" />);
    expect(frame()).toBe("20");
    expect(container.querySelector("[data-animated]")).toHaveAttribute(
      "data-animated",
      "false",
    );
    rerender(<AnimatedExpertAvatar species="fox" phase="error" />);
    expect(frame()).toBe("23");
  });
  it("stops frames when the page is hidden and resumes playback", () => {
    vi.useFakeTimers();
    const { container } = render(<AnimatedExpertAvatar phase="welcome" />);
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    act(() => vi.advanceTimersByTime(3000));
    expect(container.querySelector("[data-frame]")).toHaveAttribute(
      "data-frame",
      "2",
    );
    expect(container.querySelector("[data-animated]")).toHaveAttribute(
      "data-animated",
      "false",
    );
    hidden.mockReturnValue(false);
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    act(() => vi.advanceTimersByTime(650));
    expect(container.querySelector("[data-frame]")).toHaveAttribute(
      "data-frame",
      "3",
    );
  });
  it("honors reduced motion and labels the state accessibly", () => {
    vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList);
    const { container } = render(
      <AnimatedExpertAvatar species="owl" phase="thinking" />,
    );
    expect(container.querySelector("[data-animated]")).toHaveAttribute(
      "data-animated",
      "false",
    );
    expect(screen.getByRole("img")).toHaveAccessibleName(
      "expertAnimation.characters.owl · expertAnimation.phases.thinking",
    );
  });
});
