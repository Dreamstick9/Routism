import PosterCard from "@/components/ui/PosterCard";
import SectionLabel from "@/components/ui/SectionLabel";
import { ECOSYSTEM_LABEL, ECOSYSTEM_POSTERS } from "@/lib/content";

const ACCENTS = ["lime", "green", "pink", "blue", "signal"] as const;

/**
 * Ecosystem posters on a dark stage.
 * Motion (root SmoothScroll): data-motion="orbit" — scrub rotateY/Z on
 * [data-orbit-card] inside [data-orbit-stage]. Static grid when reduced-motion.
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
          data-orbit-stage
          className="mt-12 grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-5 md:gap-5"
          style={{ perspective: "900px" }}
        >
          {ECOSYSTEM_POSTERS.map((label, i) => {
            const tilt = i % 2 === 0 ? -2 : 2;
            const lift = i % 2 === 1 ? 12 : i % 3 === 0 ? -8 : 0;
            return (
              <div
                key={label}
                data-orbit-card
                className="will-change-transform"
                style={{
                  transform: `rotate(${tilt}deg) translateY(${lift}px)`,
                  transformStyle: "preserve-3d",
                }}
              >
                <PosterCard
                  label={label}
                  accent={ACCENTS[i % ACCENTS.length]}
                />
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
