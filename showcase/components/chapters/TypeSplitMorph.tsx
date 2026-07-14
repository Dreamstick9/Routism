import { TYPE_SPLIT_GLYPHS, TYPE_SPLIT_LABELS } from "@/lib/content";

/**
 * Static ENGINE / WORKERS crop on cream — glyph scrub deferred to PR-4b.
 * Decorative only (no nav section id).
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
            className="select-none font-black leading-[0.85] tracking-[-0.06em] text-ink"
            style={{ fontSize: "clamp(4.5rem, 18vw, 14rem)" }}
          >
            {TYPE_SPLIT_GLYPHS.engine}
          </p>
        </div>

        <div className="relative overflow-hidden text-right">
          <p
            className="select-none font-black leading-[0.85] tracking-[-0.06em] text-ink/25"
            style={{ fontSize: "clamp(4.5rem, 18vw, 14rem)" }}
          >
            {TYPE_SPLIT_GLYPHS.workers}
          </p>
        </div>
      </div>
    </section>
  );
}
