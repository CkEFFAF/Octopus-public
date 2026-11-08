import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { GripVertical } from "lucide-react";
import { useExpertOrder } from "../hooks/useExpertOrder";
import { usePinnedExperts } from "../hooks/usePinnedExperts";
import styles from "./SidebarExpertDrag.module.less";

export function SidebarDragHandle() {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      className={styles.handle}
      data-sidebar-select
      data-sidebar-drag-handle
      aria-label={t("chat.sidebarDrag.handle")}
      title={t("chat.sidebarDrag.handle")}
      onClick={(event) => event.stopPropagation()}
    >
      <GripVertical size={13} />
    </button>
  );
}

/** Pointer events keep mouse, pen and long-press touch behavior identical. */
export default function SidebarExpertDrag({
  ids,
  children,
}: {
  ids: string[];
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const { move } = useExpertOrder();
  const { movePin, pinnedIds } = usePinnedExperts();
  const root = useRef<HTMLDivElement>(null);
  const gesture = useRef<{
    id: string;
    x: number;
    y: number;
    pointer: number;
    active: boolean;
    timer: ReturnType<typeof setTimeout>;
  } | null>(null);
  const suppressClick = useRef(false);
  const [dragging, setDragging] = useState(false);
  const [over, setOver] = useState<HTMLElement | null>(null);
  const clear = () => {
    if (gesture.current) clearTimeout(gesture.current.timer);
    gesture.current = null;
    setDragging(false);
    setOver(null);
  };
  useEffect(
    () => () => {
      if (gesture.current) clearTimeout(gesture.current.timer);
    },
    [],
  );
  useEffect(() => {
    if (!over) return;
    over.dataset.dragOver = "true";
    return () => {
      delete over.dataset.dragOver;
    };
  }, [over]);
  return (
    <div
      ref={root}
      className={styles.scope}
      data-dragging={dragging}
      onContextMenu={(event) => {
        if (gesture.current?.active) event.preventDefault();
      }}
      onClickCapture={(event) => {
        if (suppressClick.current) {
          event.preventDefault();
          event.stopPropagation();
          suppressClick.current = false;
        }
      }}
      onKeyDownCapture={(event) => {
        if (event.key === "Escape") clear();
        if (
          !event.altKey ||
          !(event.target as HTMLElement).closest("[data-sidebar-drag-handle]")
        )
          return;
        const source = (event.target as HTMLElement).closest<HTMLElement>(
          "[data-sidebar-expert]",
        )?.dataset.sidebarExpert;
        if (!source) return;
        const pin = pinnedIds.includes(source);
        const list = pin ? pinnedIds : ids;
        const index = list.indexOf(source);
        if (event.key === "ArrowUp" && index > 0) {
          event.preventDefault();
          move(ids, source, list[index - 1]);
          if (pin) movePin(source, true, list[index - 1]);
        }
        if (event.key === "ArrowDown" && index < list.length - 1) {
          event.preventDefault();
          move(ids, source, list[index + 2]);
          if (pin) movePin(source, true, list[index + 2]);
        }
        if (event.key.toLowerCase() === "p") {
          event.preventDefault();
          movePin(source, !pin);
        }
      }}
      onPointerDownCapture={(event) => {
        suppressClick.current = false;
        if (event.button !== 0 || !event.isPrimary) return;
        const target = event.target as HTMLElement;
        const row = target.closest<HTMLElement>("[data-sidebar-expert]");
        if (
          !row ||
          target.closest("input,textarea,[data-no-sidebar-drag]") ||
          (target.closest("button") && !target.closest("[data-sidebar-select]"))
        )
          return;
        const id = row.dataset.sidebarExpert!;
        const pointer = event.pointerId;
        const timer = setTimeout(() => {
          if (!gesture.current) return;
          gesture.current.active = true;
          suppressClick.current = true;
          root.current?.setPointerCapture?.(pointer);
          setDragging(true);
        }, 420);
        gesture.current = {
          id,
          x: event.clientX,
          y: event.clientY,
          pointer,
          active: false,
          timer,
        };
      }}
      onPointerMove={(event) => {
        const drag = gesture.current;
        if (!drag || event.pointerId !== drag.pointer) return;
        if (!drag.active) {
          if (Math.hypot(event.clientX - drag.x, event.clientY - drag.y) > 7)
            clear();
          return;
        }
        event.preventDefault();
        const hit =
          document
            .elementFromPoint(event.clientX, event.clientY)
            ?.closest<HTMLElement>(
              "[data-sidebar-expert], [data-sidebar-zone]",
            ) ?? null;
        setOver(hit && root.current?.contains(hit) ? hit : null);
        const scroll =
          root.current?.querySelector<HTMLElement>("[data-sidebar-scroll]") ??
          (root.current?.firstElementChild as HTMLElement | undefined);
        if (scroll) {
          const box = scroll.getBoundingClientRect();
          if (event.clientY < box.top + 35) scroll.scrollTop -= 12;
          else if (event.clientY > box.bottom - 35) scroll.scrollTop += 12;
        }
      }}
      onPointerUp={(event) => {
        const drag = gesture.current;
        if (drag?.active && event.pointerId === drag.pointer) {
          const hit = document
            .elementFromPoint(event.clientX, event.clientY)
            ?.closest<HTMLElement>(
              "[data-sidebar-expert], [data-sidebar-zone]",
            );
          if (hit && root.current?.contains(hit)) {
            const pin =
              hit.closest<HTMLElement>("[data-sidebar-zone]")?.dataset
                .sidebarZone === "pinned";
            let target = hit.dataset.sidebarExpert;
            if (target && target !== drag.id) {
              const box = hit.getBoundingClientRect();
              if (event.clientY > box.top + box.height / 2) {
                const list = (pin ? pinnedIds : ids).filter(
                  (id) => id !== drag.id,
                );
                target = list[list.indexOf(target) + 1];
              }
            }
            if (target !== drag.id) {
              move(ids, drag.id, target);
              movePin(drag.id, pin, target);
            }
          }
          event.preventDefault();
          event.stopPropagation();
        }
        clear();
      }}
      onPointerCancel={clear}
    >
      {children}
      <span className={styles.status} role="status" aria-live="polite">
        {dragging ? t("chat.sidebarDrag.moving") : ""}
      </span>
    </div>
  );
}
