import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import {
  COMPOSER_HEIGHT_KEY,
  composerMaxHeight,
  composerMinHeight,
  useComposerResize,
} from "../hooks/useComposerResize";
import {
  CHAT_SIDEBAR_WIDTH_KEY,
  useChatSidebarState,
} from "../hooks/useChatSidebarState";
import ChatUsageFooter from "./ChatUsageFooter";
import { convertHistoryMessages } from "../hooks/useChat";
import { sumVisibleTurnUsage } from "../utils/chatUsage";

function ResizeFixture({ mobile = false }: { mobile?: boolean }) {
  const composer = useComposerResize(mobile);
  const sidebar = useChatSidebarState(mobile);
  return (
    <div data-chat-main>
      <div ref={sidebar.sidebarElRef} style={{ width: sidebar.sidebarWidth }}>
        <div
          role="separator"
          aria-label="sidebar"
          onPointerDown={sidebar.handleSidebarResizeStart}
          onKeyDown={sidebar.handleSidebarResizeKey}
        />
        <output>{sidebar.isSidebarResizing ? "resizing" : "settled"}</output>
      </div>
      <div data-chat-composer>
        <div ref={composer.wrapperRef} style={{ height: composer.height }}>
          <div
            role="separator"
            aria-label="composer"
            onPointerDown={composer.onPointerDown}
            onKeyDown={composer.onKeyDown}
          />
          <output>{Math.round(composer.height)}</output>
        </div>
      </div>
    </div>
  );
}

describe("chat layout sizes and usage", () => {
  const oldWidth = window.innerWidth;
  const oldHeight = window.innerHeight;
  beforeEach(() => {
    localStorage.removeItem(COMPOSER_HEIGHT_KEY);
    localStorage.removeItem(CHAT_SIDEBAR_WIDTH_KEY);
    Object.defineProperty(window, "innerWidth", {
      value: 1400,
      writable: true,
      configurable: true,
    });
    Object.defineProperty(window, "innerHeight", {
      value: 1000,
      writable: true,
      configurable: true,
    });
    vi.stubGlobal(
      "PointerEvent",
      class extends MouseEvent {
        pointerId: number;
        constructor(type: string, options: PointerEventInit) {
          super(type, options);
          this.pointerId = options.pointerId ?? 1;
        }
      },
    );
  });
  afterEach(() => {
    window.innerWidth = oldWidth;
    window.innerHeight = oldHeight;
    vi.unstubAllGlobals();
  });

  it("supports consecutive sidebar drags, keyboard widths, persistence and viewport clamp", async () => {
    const view = render(<ResizeFixture />);
    const handle = screen.getByRole("separator", { name: "sidebar" });
    fireEvent.pointerDown(handle, { button: 0, pointerId: 1, clientX: 250 });
    expect(screen.getByText("resizing")).toBeInTheDocument();
    fireEvent.pointerMove(document, { pointerId: 1, clientX: 300 });
    fireEvent.pointerUp(document, { pointerId: 1 });
    expect(localStorage.getItem(CHAT_SIDEBAR_WIDTH_KEY)).toBe("298");
    fireEvent.pointerDown(handle, { button: 0, pointerId: 2, clientX: 300 });
    expect(screen.getByText("resizing")).toBeInTheDocument();
    fireEvent.pointerMove(document, { pointerId: 2, clientX: 320 });
    fireEvent.pointerUp(document, { pointerId: 2 });
    expect(localStorage.getItem(CHAT_SIDEBAR_WIDTH_KEY)).toBe("318");
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(localStorage.getItem(CHAT_SIDEBAR_WIDTH_KEY)).toBe("338");
    vi.spyOn(handle.parentElement!, "getBoundingClientRect").mockReturnValue({
      left: 256,
      width: 338,
      height: 0,
      top: 0,
      right: 594,
      bottom: 0,
      x: 256,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    window.innerWidth = 900;
    fireEvent(window, new Event("resize"));
    await waitFor(() =>
      expect(localStorage.getItem(CHAT_SIDEBAR_WIDTH_KEY)).toBe("308"),
    );
    view.unmount();
    expect(document.body.style.userSelect).toBe("");
    expect(document.body.style.cursor).toBe("");
  });

  it("resizes the composer twice, restores its chosen height, and clamps for a smaller viewport", async () => {
    const view = render(<ResizeFixture />);
    const handle = screen.getByRole("separator", { name: "composer" });
    fireEvent.pointerDown(handle, { button: 0, pointerId: 1, clientY: 700 });
    fireEvent.pointerMove(document, { pointerId: 1, clientY: 620 });
    fireEvent.pointerUp(document, { pointerId: 1 });
    expect(localStorage.getItem(COMPOSER_HEIGHT_KEY)).toBe("260");
    fireEvent.pointerDown(handle, { button: 0, pointerId: 2, clientY: 620 });
    fireEvent.pointerMove(document, { pointerId: 2, clientY: 580 });
    fireEvent.pointerUp(document, { pointerId: 2 });
    expect(localStorage.getItem(COMPOSER_HEIGHT_KEY)).toBe("300");
    fireEvent.keyDown(handle, { key: "ArrowUp" });
    expect(localStorage.getItem(COMPOSER_HEIGHT_KEY)).toBe("320");
    view.unmount();
    render(<ResizeFixture />);
    expect(screen.getByText("320")).toBeInTheDocument();
    window.innerHeight = 280;
    fireEvent(window, new Event("resize"));
    await waitFor(() =>
      expect(localStorage.getItem(COMPOSER_HEIGHT_KEY)).toBe("120"),
    );
    expect(composerMinHeight(70)).toBeLessThanOrEqual(70);
    expect(composerMaxHeight(70)).toBeLessThanOrEqual(70);
  });

  it("cleans an interrupted drag and does not capture mobile touches", () => {
    const view = render(<ResizeFixture />);
    fireEvent.pointerDown(screen.getByRole("separator", { name: "composer" }), {
      button: 0,
      pointerId: 1,
      clientY: 700,
    });
    view.unmount();
    expect(document.body.style.userSelect).toBe("");
    expect(document.body.style.cursor).toBe("");
    render(<ResizeFixture mobile />);
    fireEvent.pointerDown(screen.getByRole("separator", { name: "composer" }), {
      button: 0,
      pointerId: 2,
      pointerType: "touch",
      clientY: 700,
    });
    fireEvent.pointerMove(document, { pointerId: 2, clientY: 600 });
    fireEvent.pointerUp(document, { pointerId: 2 });
    expect(localStorage.getItem(COMPOSER_HEIGHT_KEY)).toBe("180");
  });

  it("uses normalized turn totals once and switches usage scope with the session", () => {
    const messages = convertHistoryMessages([
      { role: "user", content: "hello", id: "u1" },
      {
        role: "assistant",
        content: "working",
        id: "a1",
        usage: {
          input_tokens: 100,
          output_tokens: 5,
          input_token_details: { cache_read: 70 },
        },
      },
      {
        role: "assistant",
        content: "done",
        id: "a2",
        usage: {
          input_tokens: 120,
          output_tokens: 6,
          input_token_details: { cache_read: 90 },
        },
      },
    ]);
    expect(sumVisibleTurnUsage([...messages, messages[2]])).toMatchObject({
      input_tokens: 220,
      output_tokens: 11,
      cache_read_tokens: 160,
      total_tokens: 231,
    });
    const view = render(
      <ChatUsageFooter messages={messages} hasMore loading={false} />,
    );
    expect(
      screen.getByText(/chatUsage.loadedMessages.*220.*160.*231/),
    ).toBeInTheDocument();
    view.rerender(
      <ChatUsageFooter messages={messages} hasMore={false} loading={false} />,
    );
    expect(screen.getByText(/chatUsage.sessionTotal.*220/)).toBeInTheDocument();
    view.rerender(
      <ChatUsageFooter messages={[]} hasMore={false} loading={false} />,
    );
    expect(screen.getByText(/chatUsage.noUsage/)).toBeInTheDocument();
    expect(screen.queryByText(/220/)).not.toBeInTheDocument();
    view.rerender(
      <ChatUsageFooter
        messages={[]}
        hasMore={false}
        loading={false}
        unavailable
      />,
    );
    expect(screen.getByText("chatUsage.unavailable")).toBeInTheDocument();
    expect(
      screen.queryByText(/chatUsage.sessionTotal/),
    ).not.toBeInTheDocument();
  });
});
