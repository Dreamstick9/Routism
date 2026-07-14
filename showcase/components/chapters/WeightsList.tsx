import SectionLabel from "@/components/ui/SectionLabel";
import {
  WEIGHTS_LABEL,
  WEIGHTS_ROWS,
  weightsModelRow,
} from "@/lib/content";
import { MODEL_ID } from "@/lib/product-facts";

/**
 * Capability rows (weights-chart analogue). Decorative — no nav section id.
 */
export default function WeightsList() {
  const rows = [...WEIGHTS_ROWS, weightsModelRow(MODEL_ID)];

  return (
    <section
      className="field-cream border-t border-black/5 bg-cream"
      aria-label="Capabilities"
    >
      <div className="mx-auto max-w-4xl px-6 py-20 md:px-10 md:py-28">
        <div data-reveal>
          <SectionLabel tone="on-light">{WEIGHTS_LABEL}</SectionLabel>
        </div>

        <ul className="mt-10 divide-y divide-black/10 border-y border-black/10">
          {rows.map((row) => (
            <li
              key={row.title}
              data-reveal
              className="flex flex-col gap-1 py-5 sm:flex-row sm:items-baseline sm:justify-between sm:gap-8"
            >
              <span className="text-lg font-semibold tracking-tight text-ink md:text-xl">
                {row.title}
              </span>
              <span className="mono text-sm text-ink/55 sm:text-right">
                {row.detail}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
