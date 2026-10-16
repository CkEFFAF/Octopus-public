import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { beginPointerDragSession } from "../../../hooks/usePointerDragSession";

export const CHAT_SIDEBAR_KEY = "octop:chat-sidebar:open";
export const CHAT_SIDEBAR_WIDTH_KEY = "octop:chat-sidebar:width";
export const SIDEBAR_WIDTH_MIN = 200;
export const SIDEBAR_WIDTH_MAX = 360;
export const SIDEBAR_WIDTH_DEFAULT = 248;
/** Viewport width at/above which the chat history rail defaults open. */
export const CHAT_SIDEBAR_WIDE_BREAKPOINT = 768;

/**
 * Resolve initial open state: explicit localStorage preference wins;
 * otherwise default open on wide viewports only. Does not react to resize.
 */
export function resolveChatSidebarDefaultOpen(
  stored: string | null,
  viewportWidth: number,
): boolean {
  if (stored === "true") return true;
  if (stored === "false") return false;
  return viewportWidth >= CHAT_SIDEBAR_WIDE_BREAKPOINT;
}

function loadSidebarWidth(): number {
  try {
    const raw = localStorage.getItem(CHAT_SIDEBAR_WIDTH_KEY);
    if (!raw) return SIDEBAR_WIDTH_DEFAULT;
    const n = Number(raw);
    if (
      Number.isFinite(n) &&
      n >= SIDEBAR_WIDTH_MIN &&
      n <= SIDEBAR_WIDTH_MAX
    ) {
      return n;
    }
  } catch {
    /* ignore */
  }
  return SIDEBAR_WIDTH_DEFAULT;
}

let sidebarOpen = (() => {
  let stored: string | null = null;
  try {
    stored = localStorage.getItem(CHAT_SIDEBAR_KEY);
  } catch {
    stored = null;
  }
  const width =
    typeof window !== "undefined" && typeof window.innerWidth === "number"
      ? window.innerWidth
      : 0;
  return resolveChatSidebarDefaultOpen(stored, width);
})();

const sidebarListeners = new Set<() => void>();

function setSidebarOpenGlobal(value: boolean | ((prev: boolean) => boolean)) {
  const next = typeof value === "function" ? value(sidebarOpen) : value;
  if (next === sidebarOpen) return;
  sidebarOpen = next;
  try {
    localStorage.setItem(CHAT_SIDEBAR_KEY, String(next));
  } catch {
    /* ignore */
  }
  for (const fn of sidebarListeners) {
    try {
      fn();
    } catch {
      /* ignore */
    }
  }
}

function subscribeSidebar(listener: () => void) {
  sidebarListeners.add(listener);
  return () => {
    sidebarListeners.delete(listener);
  };
}

function getSidebarSnapshot() {
  return sidebarOpen;
}

export function useChatSidebarOpen(): [
  boolean,
  (v: boolean | ((prev: boolean) => boolean)) => void,
] {
  const value = useSyncExternalStore(
    subscribeSidebar,
    getSidebarSnapshot,
    getSidebarSnapshot,
  );
  return [value, setSidebarOpenGlobal];
}

export function sidebarWidthBounds(viewport: number, left: number) {
  const max = Math.max(1, Math.min(SIDEBAR_WIDTH_MAX, viewport - left - 336));
  return { min: Math.min(SIDEBAR_WIDTH_MIN, max), max };
}
function clampSidebarWidth(n: number, element: HTMLElement | null): number {
  const bounds = sidebarWidthBounds(
    window.innerWidth,
    element?.getBoundingClientRect().left ?? 0,
  );
  return Math.min(bounds.max, Math.max(bounds.min, n));
}

function applySidebarWidth(el: HTMLElement | null, width: number) {
  if (!el) return;
  el.style.width = `${width}px`;
  el.style.minWidth = `${width}px`;
}

/**
 * Sidebar open/width state with a drag-to-resize handle.
 *
 * During drag we write width directly to the sidebar DOM (rAF-batched) so
 * React does not re-render SessionList on every pointermove — that was the
 * main source of jank. React state + localStorage commit only on pointerup.
 */
export function useChatSidebarState(isMobile: boolean) {
  const [sidebarOpen, setSidebarOpen] = useChatSidebarOpen();
  const [sidebarWidth, setSidebarWidth] = useState(loadSidebarWidth);
  const [isSidebarResizing, setIsSidebarResizing] = useState(false);
  const sidebarWidthRef = useRef(sidebarWidth);
  sidebarWidthRef.current = sidebarWidth;
  const sidebarElRef = useRef<HTMLDivElement>(null);
  const resizeStartRef = useRef({ x: 0, width: 0 });
  const pendingWidthRef = useRef<number | null>(null);
  const dragCleanup = useRef<(() => void) | null>(null);
  useEffect(() => () => dragCleanup.current?.(), []);
  const commitWidth = useCallback((width: number) => {
    const next = clampSidebarWidth(width, sidebarElRef.current);
    sidebarWidthRef.current = next;
    applySidebarWidth(sidebarElRef.current, next);
    setSidebarWidth(next);
    try {
      localStorage.setItem(CHAT_SIDEBAR_WIDTH_KEY, String(next));
      window.dispatchEvent(
        new CustomEvent("octop:chat-sidebar-width", { detail: next }),
      );
    } catch {
      /* unavailable */
    }
  }, []);
  useEffect(() => {
    const sync = (event: Event) => {
      const value = (event as CustomEvent<number>).detail;
      sidebarWidthRef.current = value;
      applySidebarWidth(sidebarElRef.current, value);
      setSidebarWidth(value);
    };
    window.addEventListener("octop:chat-sidebar-width", sync);
    return () => window.removeEventListener("octop:chat-sidebar-width", sync);
  }, []);
  useEffect(() => {
    if (isMobile) return;
    const clamp = () => {
      if (sidebarElRef.current) commitWidth(sidebarWidthRef.current);
    };
    clamp();
    window.addEventListener("resize", clamp);
    return () => window.removeEventListener("resize", clamp);
  }, [isMobile, commitWidth]);
  const handleSidebarResizeKey = useCallback(
    (event: React.KeyboardEvent) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      commitWidth(
        sidebarWidthRef.current + (event.key === "ArrowRight" ? 20 : -20),
      );
    },
    [commitWidth],
  );

  const handleSidebarResizeStart = useCallback(
    (e: React.PointerEvent) => {
      if (isMobile || e.button !== 0) return;
      e.preventDefault();
      e.stopPropagation();

      dragCleanup.current?.();
      dragCleanup.current = null;
      const handle = e.currentTarget as HTMLElement;
      setIsSidebarResizing(true);
      resizeStartRef.current = {
        x: e.clientX,
        width: sidebarWidthRef.current,
      };
      pendingWidthRef.current = sidebarWidthRef.current;

      dragCleanup.current = beginPointerDragSession({
        pointerId: e.pointerId,
        target: handle,
        cursor: "col-resize",
        onMove: (clientX) => {
          const next = clampSidebarWidth(
            resizeStartRef.current.width + clientX - resizeStartRef.current.x,
            sidebarElRef.current,
          );
          pendingWidthRef.current = next;
          sidebarWidthRef.current = next;
          applySidebarWidth(sidebarElRef.current, next);
        },
        onEnd: () => {
          dragCleanup.current = null;
          const finalWidth = pendingWidthRef.current ?? sidebarWidthRef.current;
          pendingWidthRef.current = null;
          setIsSidebarResizing(false);
          commitWidth(finalWidth);
        },
      });
    },
    [isMobile, commitWidth],
  );

  return {
    sidebarOpen,
    setSidebarOpen,
    sidebarWidth,
    isSidebarResizing,
    sidebarElRef,
    handleSidebarResizeStart,
    handleSidebarResizeKey,
    sidebarBounds: sidebarWidthBounds(
      window.innerWidth,
      sidebarElRef.current?.getBoundingClientRect().left ?? 0,
    ),
  };
}
