import { MARQUEE_CARDS } from "@/lib/content";

const ACCENT: Record<(typeof MARQUEE_CARDS)[number]["accent"], string> = {
  blue: "bg-accent-blue",
  pink: "bg-accent-pink",
  green: "bg-accent-green",
};

function Card({ card }: { card: (typeof MARQUEE_CARDS)[number] }) {
  return (
    <div className="flex w-44 shrink-0 flex-col overflow-hidden rounded-sm border border-white/10 bg-void sm:w-52">
      <div className={`h-2 w-full ${ACCENT[card.accent]}`} aria-hidden />
      <div className="px-5 py-6">
        <div className="text-xl font-bold tracking-tight text-paper">
          {card.title}
        </div>
        <p className="mono mt-2 text-xs text-fog-dim">{card.sub}</p>
      </div>
    </div>
  );
}

/**
 * Variant cards strip (Docker / CLI / Local).
 * Motion (root SmoothScroll): data-motion="marquee" — adds `.is-marquee-active`
 * for infinite CSS translateX on [data-marquee-track] (duration from MOTION).
 * Reduced-motion: static row, no animation class.
 */
export default function VariantsMarquee() {
  // Duplicate set for seamless −50% loop when marquee is active
  const loop = [...MARQUEE_CARDS, ...MARQUEE_CARDS];

  return (
    <section
      className="border-t border-white/5 bg-charcoal-soft py-10 md:py-14"
      aria-label="Deploy variants"
      data-motion="marquee"
    >
      {/* Static / reduced-motion: centered wrap of unique cards */}
      <div className="marquee-static mx-auto flex max-w-6xl flex-wrap items-stretch justify-center gap-4 px-6 md:gap-6 md:px-10">
        {MARQUEE_CARDS.map((card) => (
          <Card key={card.title} card={card} />
        ))}
      </div>

      {/* Infinite track — shown when SmoothScroll adds .is-marquee-active */}
      <div className="marquee-motion overflow-hidden" aria-hidden="true">
        <div
          data-marquee-track
          className="flex w-max items-stretch gap-4 px-4 md:gap-6"
        >
          {loop.map((card, i) => (
            <Card key={`${card.title}-${i}`} card={card} />
          ))}
        </div>
      </div>
    </section>
  );
}
