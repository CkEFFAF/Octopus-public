import { memo } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  ChatFilePreviewProvider,
  useChatFilePreview,
} from "./ChatFilePreviewContext";

describe("chat preview context during streaming", () => {
  it("does not refresh existing cards for unrelated tokens but updates changed actions", () => {
    const renders = vi.fn();
    const firstOpen = vi.fn();
    const nextOpen = vi.fn();
    const openCitation = vi.fn();
    const Card = memo(function Card() {
      const preview = useChatFilePreview();
      renders();
      return (
        <button
          onClick={() => preview?.openFilePreview("/project/result.txt", "gpu")}
        >
          Open result
        </button>
      );
    });
    const card = <Card />;
    const view = (open: typeof firstOpen, tokens: string) => (
      <ChatFilePreviewProvider
        openFilePreview={open}
        openKnowledgeCitation={openCitation}
      >
        {card}
        <span>{tokens}</span>
      </ChatFilePreviewProvider>
    );
    const { rerender } = render(view(firstOpen, ""));
    const initial = renders.mock.calls.length;
    for (let i = 1; i <= 20; i++) rerender(view(firstOpen, "token".repeat(i)));
    expect(renders.mock.calls.length - initial).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "Open result" }));
    expect(firstOpen).toHaveBeenCalledWith("/project/result.txt", "gpu");

    rerender(view(nextOpen, "done"));
    expect(renders.mock.calls.length - initial).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Open result" }));
    expect(nextOpen).toHaveBeenCalledWith("/project/result.txt", "gpu");
  });
});
