/**
 * Scroll target helpers used by nav and unit tests.
 * Imports section ids from product-facts (shipped source of truth).
 * Runtime scrollToSection delegates to the Lenis-aware scroll controller.
 */
import { SECTIONS, sectionHref, type SectionId } from "./product-facts";
import { scrollToSection as controllerScrollToSection } from "./scroll-controller";

export function getScrollTargets(): Record<string, string> {
  const map: Record<string, string> = {};
  for (const s of SECTIONS) {
    map[s.id] = sectionHref(s.id);
  }
  return map;
}

export function isValidSectionId(id: string): id is SectionId {
  return SECTIONS.some((s) => s.id === id);
}

/** Lenis-aware when SmoothScroll has registered; native fallback otherwise. */
export function scrollToSection(id: string): void {
  controllerScrollToSection(id);
}
