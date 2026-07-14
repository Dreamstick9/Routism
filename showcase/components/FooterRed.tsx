import {
  GITHUB_DOCS_API,
  GITHUB_DOCS_OPENAI,
  GITHUB_URL,
  SECTIONS,
} from "@/lib/product-facts";
import {
  FOOTER_COL_LICENSE,
  FOOTER_COL_NOTE,
  FOOTER_COL_PRODUCT,
  FOOTER_COL_SOURCE,
  FOOTER_DISCLAIMER,
  FOOTER_LEGAL_LINE,
  FOOTER_LINK_API,
  FOOTER_LINK_GITHUB,
  FOOTER_LINK_MIT,
  FOOTER_LINK_OPENAI,
  FOOTER_WORDMARK,
} from "@/lib/content";
import SectionLink from "@/components/SectionLink";

export default function FooterRed() {
  return (
    <footer
      className="bg-signal px-6 pb-10 pt-16 text-paper md:px-10 md:pt-20"
      aria-label="Site footer"
    >
      <div className="mx-auto grid max-w-6xl gap-10 sm:grid-cols-2 md:grid-cols-4">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.25em] text-white/70">
            {FOOTER_COL_PRODUCT}
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
            {FOOTER_COL_SOURCE}
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
                {FOOTER_LINK_GITHUB}
              </a>
            </li>
            <li>
              <a
                href={GITHUB_DOCS_API}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-sm text-white/90 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
              >
                {FOOTER_LINK_API}
              </a>
            </li>
            <li>
              <a
                href={GITHUB_DOCS_OPENAI}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-sm text-white/90 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
              >
                {FOOTER_LINK_OPENAI}
              </a>
            </li>
          </ul>
        </div>

        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.25em] text-white/70">
            {FOOTER_COL_LICENSE}
          </p>
          <ul className="mt-4 flex flex-col gap-2 text-sm">
            <li>
              <a
                href={`${GITHUB_URL}/blob/main/LICENSE`}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-sm text-white/90 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
              >
                {FOOTER_LINK_MIT}
              </a>
            </li>
          </ul>
        </div>

        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.25em] text-white/70">
            {FOOTER_COL_NOTE}
          </p>
          <p className="mt-4 text-sm leading-relaxed text-white/80">
            {FOOTER_DISCLAIMER}
          </p>
        </div>
      </div>

      <div className="mx-auto mt-16 max-w-6xl overflow-hidden border-t border-white/20 pt-8">
        <p
          className="select-none font-bold leading-[0.85] tracking-[-0.06em] text-charcoal"
          style={{ fontSize: "clamp(4rem, 18vw, 12rem)" }}
          aria-hidden
        >
          {FOOTER_WORDMARK}
        </p>
        <p className="mt-4 text-xs text-white/60">{FOOTER_LEGAL_LINE}</p>
      </div>
    </footer>
  );
}
