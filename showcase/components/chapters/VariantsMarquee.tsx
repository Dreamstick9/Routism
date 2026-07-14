import { MARQUEE_CARDS } from "@/lib/content";

const ACCENT: Record<(typeof MARQUEE_CARDS)[number]["accent"], string> = {
  blue: "bg-accent-blue",
  pink: "bg-accent-pink",
  green: "bg-accent-green",
};

/**
 * Static row of variant cards — infinite marquee deferred to PR-4b.
 * Decorative only (no nav section id).
 */
export default function VariantsMarquee() {
  return (
    <section
      className="border-t border-white/5 bg-charcoal-soft py-10 md:py-14"
      aria-label="Deploy variants"
      data-motion="marquee"
    >
      <div className="mx-auto flex max-w-6xl flex-wrap items-stretch justify-center gap-4 px-6 md:gap-6 md:px-10">
        {MARQUEE_CARDS.map((card) => (
          <div
            key={card.title}
            className="flex min-w-[10rem] flex-1 flex-col overflow-hidden rounded-sm border border-white/10 bg-void sm:max-w-[14rem]"
          >
            <div className={`h-2 w-full ${ACCENT[card.accent]}`} aria-hidden />
            <div className="px-5 py-6">
              <div className="text-xl font-bold tracking-tight text-paper">
                {card.title}
              </div>
              <p className="mono mt-2 text-xs text-fog-dim">{card.sub}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
