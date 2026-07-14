/**
 * Scroll target helpers used by nav and unit tests.
 * Imports section ids from product-facts (shipped source of truth).
 */
import { SECTIONS, sectionHref, type SectionId } from "./product-facts";

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

export function scrollToSection(id: string): void {
  if (typeof document === "undefined") return;
  const el = document.getElementById(id);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "start" });
  if (typeof history !== "undefined") {
    history.replaceState(null, "", sectionHref(id));
  }
}
