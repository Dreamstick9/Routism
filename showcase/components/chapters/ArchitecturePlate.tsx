import SectionLabel from "@/components/ui/SectionLabel";
import {
  SPLIT_CARD_ENGINE,
  SPLIT_CARD_WORKERS,
  SPLIT_ENGINE_BODY,
  SPLIT_ENGINE_SUB,
  SPLIT_H2,
  SPLIT_LABEL,
  SPLIT_SUPPORT,
  SPLIT_WORKERS_BODY,
  SPLIT_WORKERS_SUB,
} from "@/lib/content";
import { ENGINE_VS_WORKERS } from "@/lib/product-facts";

export default function ArchitecturePlate() {
  return (
    <section
      id="split"
      data-chapter
      className="relative overflow-hidden border-t border-white/5 bg-charcoal"
      aria-labelledby="split-title"
    >
      {/* Solid abstract plate — parallax bg deferred to PR-4a */}
      <div
        data-motion="parallax"
        className="pointer-events-none absolute inset-0 bg-gradient-to-br from-charcoal via-charcoal-soft to-void"
        aria-hidden
      />
      <div
        className="pointer-events-none absolute -right-24 top-1/4 h-72 w-72 rounded-full border border-white/10"
        aria-hidden
      />
      <div
        className="pointer-events-none absolute -left-16 bottom-1/4 h-48 w-48 rounded-full border border-white/5"
        aria-hidden
      />

      <div className="section-pad relative z-[1] mx-auto grid max-w-5xl gap-10 md:grid-cols-2 md:items-center">
        <div>
          <div data-reveal>
            <SectionLabel>{SPLIT_LABEL}</SectionLabel>
          </div>
          <h2
            id="split-title"
            data-reveal
            className="mt-4 text-4xl font-bold tracking-tight text-paper md:text-5xl"
          >
            {SPLIT_H2}
          </h2>
          <p data-reveal className="mt-6 leading-relaxed text-fog">
            {ENGINE_VS_WORKERS}
          </p>
          <p
            data-reveal
            className="mt-4 text-sm leading-relaxed text-fog-dim"
          >
            {SPLIT_SUPPORT}
          </p>
        </div>

        <div data-reveal className="grid gap-4">
          <div className="rounded-sm border border-white/10 bg-charcoal-soft p-6">
            <div className="text-[11px] font-medium uppercase tracking-[0.25em] text-signal-hot">
              {SPLIT_CARD_ENGINE}
            </div>
            <div className="mt-2 font-semibold text-paper">{SPLIT_ENGINE_SUB}</div>
            <p className="mt-2 text-sm text-fog-dim">{SPLIT_ENGINE_BODY}</p>
          </div>
          <div className="rounded-sm border border-white/10 bg-charcoal-soft p-6">
            <div className="text-[11px] font-medium uppercase tracking-[0.25em] text-paper/80">
              {SPLIT_CARD_WORKERS}
            </div>
            <div className="mt-2 font-semibold text-paper">{SPLIT_WORKERS_SUB}</div>
            <p className="mt-2 text-sm text-fog-dim">{SPLIT_WORKERS_BODY}</p>
          </div>
        </div>
      </div>
    </section>
  );
}
