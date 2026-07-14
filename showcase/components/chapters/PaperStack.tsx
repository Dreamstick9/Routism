import { PAPER_STACK_CARDS } from "@/lib/content";

const ACCENT_BG: Record<(typeof PAPER_STACK_CARDS)[number]["accent"], string> = {
  lime: "bg-accent-lime",
  green: "bg-accent-green",
  signal: "bg-signal",
};

/** Static stacked paper cards — fan motion deferred to PR-4b. */
export default function PaperStack() {
  return (
    <div
      className="relative mx-auto flex min-h-[16rem] w-full max-w-md items-center justify-center py-8"
      data-motion="fan"
      aria-label="Plan, Execute, Merge"
    >
      <ul className="relative mx-auto h-52 w-full max-w-xs list-none">
        {PAPER_STACK_CARDS.map((card, i) => {
          /* Static pre-fan pose: slight rotate + offset */
          const rotate = (i - 1) * 6;
          const x = (i - 1) * 18;
          const y = i * 8;
          const z = 10 + i;
          return (
            <li
              key={card.title}
              className="absolute left-[7.5%] top-0 w-[85%] overflow-hidden rounded-sm border border-black/10 bg-cream-deep shadow-[0_8px_32px_rgba(0,0,0,0.12)]"
              style={{
                transform: `translateX(${x}px) translateY(${y}px) rotate(${rotate}deg)`,
                zIndex: z,
              }}
            >
              <div className={`h-2 w-full ${ACCENT_BG[card.accent]}`} aria-hidden />
              <div className="px-5 py-6">
                <div className="text-2xl font-bold tracking-tight text-ink">
                  {card.title}
                </div>
                <p className="mt-2 text-sm leading-relaxed text-ink/70">
                  {card.body}
                </p>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
