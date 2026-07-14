import SectionLabel from "@/components/ui/SectionLabel";
import {
  PROOF_DOCS_API,
  PROOF_DOCS_LEAD,
  PROOF_DOCS_OPENAI,
  PROOF_H2,
  PROOF_LABEL,
} from "@/lib/content";
import {
  GITHUB_DOCS_API,
  GITHUB_DOCS_OPENAI,
  PROOF_CARDS,
} from "@/lib/product-facts";

export default function ProofCards() {
  return (
    <section
      id="proof"
      data-chapter
      className="border-t border-white/5 bg-void"
      aria-labelledby="proof-title"
    >
      <div className="section-pad mx-auto max-w-5xl">
        <div data-reveal>
          <SectionLabel>{PROOF_LABEL}</SectionLabel>
        </div>
        <h2
          id="proof-title"
          data-reveal
          className="mt-4 text-4xl font-bold tracking-tight text-paper"
        >
          {PROOF_H2}
        </h2>

        <div className="mt-10 grid gap-4 sm:grid-cols-2">
          {PROOF_CARDS.map((c, i) => (
            <article
              key={c.title}
              data-reveal
              className="overflow-hidden rounded-sm border border-white/10 bg-charcoal-soft"
            >
              <div
                className={`h-1 w-full ${
                  i % 4 === 0
                    ? "bg-accent-lime"
                    : i % 4 === 1
                      ? "bg-accent-green"
                      : i % 4 === 2
                        ? "bg-accent-pink"
                        : "bg-accent-blue"
                }`}
                aria-hidden
              />
              <div className="p-6">
                <h3 className="text-lg font-semibold text-paper">{c.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-fog-dim">
                  {c.body}
                </p>
              </div>
            </article>
          ))}
        </div>

        <p data-reveal className="mt-8 text-sm text-fog-dim">
          {PROOF_DOCS_LEAD}{" "}
          <a
            href={GITHUB_DOCS_OPENAI}
            className="text-paper hover:underline"
            target="_blank"
            rel="noopener noreferrer"
          >
            {PROOF_DOCS_OPENAI}
          </a>
          {" · "}
          <a
            href={GITHUB_DOCS_API}
            className="text-paper hover:underline"
            target="_blank"
            rel="noopener noreferrer"
          >
            {PROOF_DOCS_API}
          </a>
        </p>
      </div>
    </section>
  );
}
