/**
 * Motion constants + helpers for SmoothScroll (single ST owner).
 * Chapters stay markup-only: data-motion / data-chapter / data-reveal.
 */

export const MOTION = {
  lenisDuration: 1.15,
  navOffset: -72,
  reveal: {
    y: 32,
    duration: 0.85,
    stagger: 0.06,
    ease: "power3.out",
  },
  heroReveal: {
    y: 24,
    duration: 0.9,
    stagger: 0.08,
    ease: "power3.out",
    delay: 0.1,
  },
  /** Parallax plate (PR-4a): scrub yPercent −intensity → +intensity */
  parallax: {
    yPercent: 15,
    /** Desktop-only; never pin/parallax under this width */
    minWidthPx: 768,
  },
  /** PR-4b placeholders — not registered while tiers.advanced is false */
  glyphPin: { end: "+=180%" },
  marqueeSeconds: 48,
  tiers: {
    parallax: true,
    advanced: false,
  },
} as const;

/** Attribute vocabulary for root SmoothScroll registration. */
export type MotionAttr =
  | "parallax"
  | "orbit"
  | "glyph-scrub"
  | "fan"
  | "marquee"
  | "reveal-hero";

/** True when OS/browser requests reduced motion. */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return true;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Desktop viewport and motion allowed (parallax / pin gate). */
export function canRunDesktopMotion(): boolean {
  if (typeof window === "undefined") return false;
  if (prefersReducedMotion()) return false;
  return window.matchMedia(
    `(min-width: ${MOTION.parallax.minWidthPx}px)`,
  ).matches;
}

/**
 * Dev-only ScrollTrigger markers when URL has `?debugMotion=1`.
 * Never default in production builds unless query is present.
 */
export function isDebugMotion(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return new URLSearchParams(window.location.search).get("debugMotion") === "1";
  } catch {
    return false;
  }
}
