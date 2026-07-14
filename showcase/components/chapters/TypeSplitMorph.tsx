import { TYPE_SPLIT_GLYPHS, TYPE_SPLIT_LABELS } from "@/lib/content";

/**
 * ENGINE / WORKERS crop on cream.
 * Motion (root SmoothScroll): data-motion="glyph-scrub" — pin + scrub
 * translateX on [data-glyph], desktop-only. Static crop when reduced-motion
 * or mobile (no pin).
 */
export default function TypeSplitMorph() {
  return (
    <section
      className="field-cream relative overflow-hidden border-t border-black/5 bg-cream py-20 md:py-28"
      aria-label="Engine and workers type split"
      data-motion="glyph-scrub"
    >
      <div className="relative mx-auto flex max-w-6xl flex-col items-stretch gap-6 px-6 md:px-10">
        <div className="flex justify-between text-[11px] font-medium uppercase tracking-[0.28em] text-ink/50">
          <span>{TYPE_SPLIT_LABELS.left}</span>
          <span>{TYPE_SPLIT_LABELS.right}</span>
        </div>

        <div className="relative overflow-hidden">
          <p
            data-glyph
            className="select-none font-black leading-[0.85] tracking-[-0.06em] text-ink will-change-transform"
            style={{ fontSize: "clamp(4.5rem, 18vw, 14rem)" }}
          >
            {TYPE_SPLIT_GLYPHS.engine}
          </p>
        </div>

        <div className="relative overflow-hidden text-right">
          <p
            data-glyph
            className="select-none font-black leading-[0.85] tracking-[-0.06em] text-ink/25 will-change-transform"
            style={{ fontSize: "clamp(4.5rem, 18vw, 14rem)" }}
          >
            {TYPE_SPLIT_GLYPHS.workers}
          </p>
        </div>
      </div>
    </section>
  );
}
