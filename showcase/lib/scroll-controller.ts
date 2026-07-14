/**
 * Singleton Lenis-aware scroll controller.
 * SmoothScroll registers the scroller; Nav / hash links call scrollToSection.
 */

import { sectionHref } from "./product-facts";

export type Scroller = {
  scrollTo: (
    target: string | Element,
    opts?: { offset?: number; immediate?: boolean; force?: boolean },
  ) => void;
  onScroll: (cb: (y: number) => void) => () => void;
  refresh: () => void;
  /** Pause smooth scrolling (e.g. while a modal is open). */
  stop: () => void;
  /** Resume smooth scrolling after stop(). */
  start: () => void;
};

const DEFAULT_NAV_OFFSET = -72;

type ScrollCb = (y: number) => void;

let scroller: Scroller | null = null;

/** Active spy subscribers that should rebind when scroller is set/cleared. */
const scrollCbs = new Set<ScrollCb>();
/** Per-cb teardown for the current binding (Lenis unsub and/or window listener). */
const cbTeardowns = new Map<ScrollCb, () => void>();

function bindScrollCb(cb: ScrollCb): void {
  const prev = cbTeardowns.get(cb);
  if (prev) {
    prev();
    cbTeardowns.delete(cb);
  }

  const s = scroller;
  if (s) {
    const unsub = s.onScroll(cb);
    cbTeardowns.set(cb, unsub);
    return;
  }

  if (typeof window === "undefined") return;
  const handler = () => cb(window.scrollY);
  window.addEventListener("scroll", handler, { passive: true });
  cbTeardowns.set(cb, () => window.removeEventListener("scroll", handler));
}

function rebindAllScrollCbs(): void {
  for (const cb of scrollCbs) {
    bindScrollCb(cb);
  }
}

export function setScroller(s: Scroller | null): void {
  scroller = s;
  // Re-bind all subscribers when Lenis appears/disappears (child effects may
  // have subscribed before the parent SmoothScroll effect ran).
  rebindAllScrollCbs();
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
    // force: true so scroll works even when Lenis is stop()'d (mobile sheet lock)
    s.scrollTo(el, { offset, immediate: false, force: true });
  } else if (typeof window !== "undefined") {
    // Match Lenis offset so fixed chrome does not cover headings
    const top = el.getBoundingClientRect().top + window.scrollY + offset;
    window.scrollTo({ top, behavior: "smooth" });
  }

  if (typeof history !== "undefined") {
    history.replaceState(null, "", sectionHref(id));
  }
}

/**
 * Subscribe to scroll position for nav spy.
 * Uses Lenis when registered; falls back to window scroll.
 * Rebinds automatically when setScroller is called later.
 * Returns an unsubscribe function.
 */
export function subscribeScroll(cb: ScrollCb): () => void {
  scrollCbs.add(cb);
  bindScrollCb(cb);
  // Initial reading for consumers that need an immediate value
  if (typeof window !== "undefined") {
    cb(window.scrollY);
  }
  return () => {
    scrollCbs.delete(cb);
    const teardown = cbTeardowns.get(cb);
    if (teardown) {
      teardown();
      cbTeardowns.delete(cb);
    }
  };
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
