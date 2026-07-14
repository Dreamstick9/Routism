import PaperStack from "@/components/chapters/PaperStack";
import SectionLabel from "@/components/ui/SectionLabel";
import { HOOK_BODY, HOOK_LABEL, HOOK_STACK_LINES } from "@/lib/content";
import { PRODUCT_HOOK } from "@/lib/product-facts";

export default function StoryHook() {
  return (
    <section
      id="hook"
      data-chapter
      className="border-t border-white/5 bg-void"
      aria-labelledby="hook-title"
    >
      <div className="section-pad mx-auto grid max-w-6xl gap-12 md:grid-cols-2 md:items-center md:gap-16">
        <div>
          <div data-reveal>
            <SectionLabel>{HOOK_LABEL}</SectionLabel>
          </div>
          <div
            data-reveal
            className="mt-6 space-y-1 border-l border-white/15 pl-6 md:pl-8"
          >
            {HOOK_STACK_LINES.map((line) => (
              <p
                key={line}
                className="font-bold leading-[0.92] tracking-[-0.04em] text-paper"
                style={{ fontSize: "clamp(2.75rem, 8vw, 5.5rem)" }}
              >
                {line}
              </p>
            ))}
          </div>
          <h2
            id="hook-title"
            data-reveal
            className="mt-10 max-w-xl text-xl font-semibold leading-snug tracking-tight text-paper md:text-2xl"
          >
            {PRODUCT_HOOK}
          </h2>
          <p
            data-reveal
            className="mt-6 max-w-xl text-base leading-relaxed text-fog md:text-lg"
          >
            {HOOK_BODY}
          </p>
        </div>

        <div data-reveal className="field-cream rounded-sm bg-cream px-4 py-6 md:px-8 md:py-10">
          <PaperStack />
        </div>
      </div>
    </section>
  );
}
