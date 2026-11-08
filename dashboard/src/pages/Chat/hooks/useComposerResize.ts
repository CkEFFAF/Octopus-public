import { useCallback, useEffect, useRef, useState } from "react";
import { beginPointerDragSession } from "../../../hooks/usePointerDragSession";

export const COMPOSER_HEIGHT_KEY = "octop:chat-composer:height";
export const COMPOSER_MIN_HEIGHT = 120;
export function composerMinHeight(available: number): number {
  return Math.max(
    1,
    Math.min(
      COMPOSER_MIN_HEIGHT,
      available,
      available < 240 ? 88 : COMPOSER_MIN_HEIGHT,
    ),
  );
}
export function composerMaxHeight(available: number): number {
  return Math.max(
    composerMinHeight(available),
    Math.min(520, available * 0.55, available - 160),
  );
}

export function useComposerResize(isMobile: boolean) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState(() => {
    try {
      const value = Number(localStorage.getItem(COMPOSER_HEIGHT_KEY));
      if (Number.isFinite(value) && value >= COMPOSER_MIN_HEIGHT) return value;
    } catch {
      /* storage unavailable */
    }
    return isMobile ? 152 : 132;
  });
  const heightRef = useRef(height);
  heightRef.current = height;
  const [maxHeight, setMaxHeight] = useState(520);
  const maxRef = useRef(maxHeight);
  const [minHeight, setMinHeight] = useState(COMPOSER_MIN_HEIGHT);
  const minRef = useRef(minHeight);
  const cleanupRef = useRef<(() => void) | null>(null);
  const clamp = useCallback(
    (value: number) =>
      Math.max(minRef.current, Math.min(maxRef.current, value)),
    [],
  );
  const commit = useCallback(
    (value: number) => {
      const next = clamp(value);
      heightRef.current = next;
      setHeight(next);
      if (wrapperRef.current) wrapperRef.current.style.height = `${next}px`;
      try {
        localStorage.setItem(COMPOSER_HEIGHT_KEY, String(next));
      } catch {
        /* storage unavailable */
      }
    },
    [clamp],
  );
  useEffect(() => {
    const wrapper = wrapperRef.current;
    const parent = wrapper?.closest("[data-chat-main]");
    const resize = () => {
      const viewport = window.visualViewport?.height ?? window.innerHeight;
      const parentHeight = parent?.getBoundingClientRect().height || viewport;
      const shell = wrapperRef.current?.closest("[data-chat-composer]");
      const fixedChrome = parent
        ? Array.from(parent.children).reduce((sum, child) => {
            if (child === shell || !(child instanceof HTMLElement)) return sum;
            const style = getComputedStyle(child);
            return style.display !== "none" &&
              style.position !== "absolute" &&
              style.position !== "fixed" &&
              Number(style.flexGrow) === 0
              ? sum + child.getBoundingClientRect().height
              : sum;
          }, 0)
        : 0;
      const shellExtra =
        shell && wrapperRef.current
          ? Math.max(
              0,
              shell.getBoundingClientRect().height -
                wrapperRef.current.getBoundingClientRect().height,
            )
          : 0;
      const available = Math.max(
        1,
        Math.min(viewport, parentHeight) - fixedChrome - shellExtra,
      );
      const compact =
        (parent?.getBoundingClientRect().width || window.innerWidth) <= 560;
      const pixels = (value: string) => Number.parseFloat(value) || 0;
      const wrapperStyle = wrapper && getComputedStyle(wrapper);
      const contentMinimum = wrapperStyle
        ? pixels(wrapperStyle.paddingTop) +
          pixels(wrapperStyle.paddingBottom) +
          pixels(wrapperStyle.borderTopWidth) +
          pixels(wrapperStyle.borderBottomWidth) +
          36 +
          Array.from(
            wrapper.querySelectorAll<HTMLElement>("[data-composer-fixed]"),
          ).reduce((sum, child) => {
            const style = getComputedStyle(child);
            if (style.display === "none") return sum;
            // Reserve one full attachment row; extra rows remain scrollable.
            const childHeight = child.hasAttribute("data-composer-preview")
              ? Math.min(child.scrollHeight, 96)
              : child.getBoundingClientRect().height;
            return (
              sum +
              childHeight +
              pixels(style.marginTop) +
              pixels(style.marginBottom)
            );
          }, 0)
        : 0;
      const min = Math.max(
        composerMinHeight(available),
        compact ? Math.min(152, available) : 0,
        Math.min(Math.ceil(contentMinimum), available),
      );
      minRef.current = min;
      setMinHeight(min);
      const limit = Math.max(min, composerMaxHeight(available));
      maxRef.current = limit;
      setMaxHeight(limit);
      commit(heightRef.current);
    };
    resize();
    const observer = new ResizeObserver(resize);
    if (parent) observer.observe(parent);
    const observeContent = () => {
      wrapper
        ?.querySelectorAll("[data-composer-fixed]")
        .forEach((child) => observer.observe(child));
      resize();
    };
    observeContent();
    const mutations = new MutationObserver(observeContent);
    if (wrapper) mutations.observe(wrapper, { childList: true });
    window.addEventListener("resize", resize);
    window.visualViewport?.addEventListener("resize", resize);
    return () => {
      cleanupRef.current?.();
      observer.disconnect();
      mutations.disconnect();
      window.removeEventListener("resize", resize);
      window.visualViewport?.removeEventListener("resize", resize);
    };
  }, [commit]);
  const onPointerDown = useCallback(
    (event: React.PointerEvent) => {
      if (isMobile || event.pointerType === "touch" || event.button !== 0)
        return;
      event.preventDefault();
      event.stopPropagation();
      cleanupRef.current?.();
      const startY = event.clientY;
      const startHeight = heightRef.current;
      cleanupRef.current = beginPointerDragSession({
        pointerId: event.pointerId,
        target: event.currentTarget as HTMLElement,
        cursor: "row-resize",
        onMove: (_x, y) => {
          const next = clamp(startHeight + startY - y);
          heightRef.current = next;
          if (wrapperRef.current) wrapperRef.current.style.height = `${next}px`;
        },
        onEnd: () => {
          cleanupRef.current = null;
          commit(heightRef.current);
        },
      });
    },
    [clamp, commit, isMobile],
  );
  const onKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
      event.preventDefault();
      commit(heightRef.current + (event.key === "ArrowUp" ? 20 : -20));
    },
    [commit],
  );
  return { wrapperRef, height, minHeight, maxHeight, onPointerDown, onKeyDown };
}
