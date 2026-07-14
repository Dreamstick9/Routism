/**
 * Singleton Lenis-aware scroll controller.
 * SmoothScroll registers the scroller; Nav / hash links call scrollToSection.
 */

import { sectionHref } from "./product-facts";

export type Scroller = {
  scrollTo: (
    target: string | Element,
    opts?: { offset?: number; immediate?: boolean },
  ) => void;
  onScroll: (cb: (y: number) => void) => () => void;
  refresh: () => void;
};

const DEFAULT_NAV_OFFSET = -72;

let scroller: Scroller | null = null;

export function setScroller(s: Scroller | null): void {
  scroller = s;
}

export function getScroller(): Scroller | null {
  return scroller;
}

/** Scroll to a section by id; Lenis when available, native otherwise. */
export function scrollToSection(id: string, offset = DEFAULT_NAV_OFFSET): void {
  if (typeof document === "undefined") return;
  const el = document.getElementById(id);
  if (!el) return;

  const s = getScroller();
  if (s) {
    s.scrollTo(el, { offset, immediate: false });
  } else {
    el.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  if (typeof history !== "undefined") {
    history.replaceState(null, "", sectionHref(id));
  }
}

/**
 * Subscribe to scroll position for nav spy.
 * Uses Lenis when registered; falls back to window scroll.
 * Returns an unsubscribe function.
 */
export function subscribeScroll(cb: (y: number) => void): () => void {
  const s = getScroller();
  if (s) {
    return s.onScroll(cb);
  }
  if (typeof window === "undefined") {
    return () => {};
  }
  const handler = () => cb(window.scrollY);
  handler();
  window.addEventListener("scroll", handler, { passive: true });
  return () => window.removeEventListener("scroll", handler);
}

/**
 * Resolve which section is active given scroll position.
 * Threshold: section top ≤ 0.35 * viewport (matches prior Nav logic).
 */
export function resolveActiveSection(
  ids: readonly string[],
  viewportHeight?: number,
): string {
  if (typeof document === "undefined" || !ids.length) {
    return ids[0] ?? "";
  }
  const vh =
    viewportHeight ??
    (typeof window !== "undefined" ? window.innerHeight : 800);
  let current = ids[0];
  for (const id of ids) {
    const el = document.getElementById(id);
    if (!el) continue;
    const top = el.getBoundingClientRect().top;
    if (top <= vh * 0.35) current = id;
  }
  return current;
}
