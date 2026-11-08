// One shared pointer listener keeps large conversation histories inexpensive.
const avatars = new Map<HTMLElement, (near: boolean) => void>();
let active: HTMLElement | null = null;
let frame = 0;
let point = { x: 0, y: 0 };

function select(next: HTMLElement | null) {
  if (next === active) return;
  if (active) avatars.get(active)?.(false);
  active = next;
  if (active) avatars.get(active)?.(true);
}

function update() {
  frame = 0;
  let nearest: HTMLElement | null = null;
  let distance = 38;
  for (const element of avatars.keys()) {
    const rect = element.getBoundingClientRect();
    if (
      !rect.width ||
      !rect.height ||
      rect.bottom < 0 ||
      rect.top > innerHeight
    )
      continue;
    const dx = Math.max(rect.left - point.x, 0, point.x - rect.right);
    const dy = Math.max(rect.top - point.y, 0, point.y - rect.bottom);
    const d = Math.hypot(dx, dy);
    if (d < distance) {
      distance = d;
      nearest = element;
    }
  }
  select(nearest);
}

function pointerMove(event: PointerEvent) {
  if (event.pointerType === "touch") return;
  point = { x: event.clientX, y: event.clientY };
  if (!frame) frame = requestAnimationFrame(update);
}
function clear() {
  if (frame) cancelAnimationFrame(frame);
  frame = 0;
  select(null);
}
function pointerOut(event: PointerEvent) {
  if (!event.relatedTarget) clear();
}

export function observeProximity(
  element: HTMLElement,
  callback: (near: boolean) => void,
) {
  if (!avatars.size) {
    window.addEventListener("pointermove", pointerMove, { passive: true });
    window.addEventListener("blur", clear);
    window.addEventListener("scroll", clear, true);
    document.addEventListener("pointerout", pointerOut);
  }
  avatars.set(element, callback);
  return () => {
    if (active === element) {
      active = null;
      callback(false);
    }
    avatars.delete(element);
    if (!avatars.size) {
      clear();
      window.removeEventListener("pointermove", pointerMove);
      window.removeEventListener("blur", clear);
      window.removeEventListener("scroll", clear, true);
      document.removeEventListener("pointerout", pointerOut);
    }
  };
}
