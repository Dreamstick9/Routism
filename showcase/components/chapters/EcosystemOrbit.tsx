import PosterCard from "@/components/ui/PosterCard";
import SectionLabel from "@/components/ui/SectionLabel";
import { ECOSYSTEM_LABEL, ECOSYSTEM_POSTERS } from "@/lib/content";

const ACCENTS = ["lime", "green", "pink", "blue", "signal"] as const;

/**
 * Static grid of ecosystem posters — orbit motion deferred to PR-4b.
 * Decorative only (no nav section id).
 */
export default function EcosystemOrbit() {
  return (
    <section
      className="border-t border-white/5 bg-void py-20 md:py-28"
      aria-label="Ecosystem"
      data-motion="orbit"
    >
      <div className="mx-auto max-w-6xl px-6 md:px-10">
        <div data-reveal className="text-center">
          <SectionLabel>{ECOSYSTEM_LABEL}</SectionLabel>
        </div>

        <div
          data-reveal
          className="mt-12 grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-5 md:gap-5"
        >
          {ECOSYSTEM_POSTERS.map((label, i) => {
            const tilt = i % 2 === 0 ? -2 : 2;
            const lift = i % 2 === 1 ? 12 : i % 3 === 0 ? -8 : 0;
            return (
              <PosterCard
                key={label}
                label={label}
                accent={ACCENTS[i % ACCENTS.length]}
                style={{
                  transform: `rotate(${tilt}deg) translateY(${lift}px)`,
                }}
              />
            );
          })}
        </div>
      </div>
    </section>
  );
}
