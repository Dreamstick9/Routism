/**
 * Motion constants + helpers for SmoothScroll (single ST owner).
 * Chapters stay markup-only: data-motion / data-chapter / data-reveal.
 *
 * Motion values (data-motion vocabulary):
 * - parallax     — ArchitecturePlate bg plate; scrub yPercent (PR-4a)
 * - glyph-scrub  — TypeSplitMorph; pin + scrub translateX (desktop-only)
 * - fan          — PaperStack cards; enter stack → −6° / 0° / 6°
 * - orbit        — EcosystemOrbit posters; scrub rotateY/Z ±8–18°
 * - marquee      — VariantsMarquee; infinite CSS translateX
 * - reveal-hero  — hero enter (handled as #world load timeline)
 *
 * tiers.advanced gates glyph/fan/orbit/marquee. Reduced-motion skips all
 * advanced (and Lenis/ST entirely) via prefersReducedMotion early-return.
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
  /**
   * Glyph pin/scrub (PR-4b, data-motion="glyph-scrub"):
   * Pin section for ~180% viewport; scrub giant glyphs opposite translateX.
   * Desktop-only (matchMedia min-width + no reduced-motion).
   */
  glyphPin: {
    end: "+=180%",
    /** Horizontal scrub range as xPercent for ENGINE / WORKERS lines */
    xPercent: 28,
  },
  /**
   * Paper stack fan (PR-4b, data-motion="fan"):
   * On enter: stacked → final rotates −6° / 0° / 6°.
   */
  fan: {
    duration: 1.0,
    ease: "power2.out",
    /** Final rotate per card index 0..2 → (i - 1) * angle */
    angleDeg: 6,
    /** Final translateX per card: (i - 1) * xPx */
    xPx: 18,
    /** Final translateY per card: i * yPx */
    yPx: 8,
    start: "top 75%",
  },
  /**
   * Ecosystem orbit (PR-4b, data-motion="orbit"):
   * Scrub rotateY/Z across section; amplitude ±rotateY / ±rotateZ.
   */
  orbit: {
    perspectivePx: 900,
    rotateY: 14,
    rotateZ: 10,
  },
  /**
   * Marquee (PR-4b, data-motion="marquee"):
   * Infinite CSS translateX; duration in seconds (linear).
   */
  marqueeSeconds: 48,
  tiers: {
    parallax: true,
    /** PR-4b: glyph-scrub, fan, orbit, marquee */
    advanced: true,
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
