import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AnimatedExpertAvatar from ".";
afterEach(() => vi.restoreAllMocks());
describe("native GIF playback", () => {
  it("switches clips when real work changes and falls back to a static frame on load failure", () => {
    const { rerender } = render(
      <AnimatedExpertAvatar species="fox" phase="coding" />,
    );
    expect(screen.getByRole("img")).toHaveAttribute(
      "src",
      "/expert-animations/v2/fox/working.gif",
    );
    rerender(<AnimatedExpertAvatar species="fox" phase="waiting_permission" />);
    expect(screen.getByRole("img")).toHaveAttribute(
      "src",
      "/expert-animations/v2/fox/waiting.gif",
    );
    fireEvent.error(screen.getByRole("img"));
    expect(screen.getByRole("img")).toHaveAttribute(
      "src",
      "/expert-animations/v2/fox/waiting.png",
    );
  });
  it("uses still images in hidden tabs and resumes the same action", () => {
    render(<AnimatedExpertAvatar species="owl" phase="thinking" />);
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(screen.getByRole("img")).toHaveAttribute(
      "src",
      "/expert-animations/v2/owl/thinking.png",
    );
    hidden.mockReturnValue(false);
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(screen.getByRole("img")).toHaveAttribute(
      "src",
      "/expert-animations/v2/owl/thinking.gif",
    );
  });
  it("honors reduced motion and keeps the accessible phase label", () => {
    vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList);
    render(<AnimatedExpertAvatar species="dragon" phase="thinking" />);
    expect(screen.getByRole("img")).toHaveAttribute(
      "src",
      "/expert-animations/v2/dragon/thinking.png",
    );
    expect(screen.getByRole("img")).toHaveAccessibleName(
      "expertAnimation.characters.dragon · expertAnimation.phases.thinking",
    );
  });
});
