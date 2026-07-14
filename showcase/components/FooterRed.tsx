import {
  GITHUB_DOCS_API,
  GITHUB_DOCS_OPENAI,
  GITHUB_URL,
  SECTIONS,
} from "@/lib/product-facts";
import SectionLink from "@/components/SectionLink";

const FOOTER_DISCLAIMER =
  "Showcase site only — product dashboard runs after you install locally. Not a multi-tenant SaaS; no OAuth or Stripe required.";

export default function FooterRed() {
  return (
    <footer
      className="bg-[var(--signal,#E31C23)] px-6 pb-10 pt-16 text-[var(--paper,#FFFFFF)] md:px-10 md:pt-20"
      aria-label="Site footer"
    >
      <div className="mx-auto grid max-w-6xl gap-10 sm:grid-cols-2 md:grid-cols-4">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.25em] text-white/70">
            Product
          </p>
          <ul className="mt-4 flex flex-col gap-2 text-sm">
            {SECTIONS.map((s) => (
              <li key={s.id}>
                <SectionLink
                  id={s.id}
                  className="rounded-sm text-white/90 transition-opacity hover:opacity-100 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
                >
                  {s.label}
                </SectionLink>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.25em] text-white/70">
            Source
          </p>
          <ul className="mt-4 flex flex-col gap-2 text-sm">
            <li>
              <a
                href={GITHUB_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-sm text-white/90 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
                data-github-url={GITHUB_URL}
                data-cta="github-footer"
              >
                GitHub
              </a>
            </li>
            <li>
              <a
                href={GITHUB_DOCS_API}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-sm text-white/90 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
              >
                API docs
              </a>
            </li>
            <li>
              <a
                href={GITHUB_DOCS_OPENAI}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-sm text-white/90 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
              >
                OpenAI compat
              </a>
            </li>
          </ul>
        </div>

        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.25em] text-white/70">
            License
          </p>
          <ul className="mt-4 flex flex-col gap-2 text-sm">
            <li>
              <a
                href={`${GITHUB_URL}/blob/main/LICENSE`}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-sm text-white/90 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
              >
                MIT
              </a>
            </li>
          </ul>
        </div>

        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.25em] text-white/70">
            Note
          </p>
          <p className="mt-4 text-sm leading-relaxed text-white/80">
            {FOOTER_DISCLAIMER}
          </p>
        </div>
      </div>

      <div className="mx-auto mt-16 max-w-6xl overflow-hidden border-t border-white/20 pt-8">
        <p
          className="select-none font-bold leading-[0.85] tracking-[-0.06em] text-[var(--charcoal,#1A1A1A)]"
          style={{ fontSize: "clamp(4rem, 18vw, 12rem)" }}
          aria-hidden
        >
          ROUTISM
        </p>
        <p className="mt-4 text-xs text-white/60">
          MIT licensed · self-hosted · not a multi-tenant SaaS
        </p>
      </div>
    </footer>
  );
}
