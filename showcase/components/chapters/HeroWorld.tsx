"use client";

import SectionLink from "@/components/SectionLink";
import DisplayCrop from "@/components/ui/DisplayCrop";
import SectionLabel from "@/components/ui/SectionLabel";
import {
  CTA_GET_ROUTISM,
  CTA_SEE_INSTALL,
  HERO_CROP,
  HERO_H1_LINES,
  HERO_LABEL,
  heroMetaLine,
} from "@/lib/content";
import {
  GITHUB_URL,
  INSTALL_COMMAND,
  MODEL_ID,
  PRODUCT_ONE_LINER,
} from "@/lib/product-facts";
import { track } from "@/lib/analytics";

export default function HeroWorld() {
  return (
    <section
      id="world"
      data-chapter
      data-motion="reveal-hero"
      className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-signal px-6 pb-24 pt-28 text-center"
      aria-label="Hero"
    >
      {/* Abstract SVG ring ornament */}
      <svg
        className="pointer-events-none absolute left-1/2 top-1/2 h-[min(80vw,40rem)] w-[min(80vw,40rem)] -translate-x-1/2 -translate-y-1/2 opacity-[0.12]"
        viewBox="0 0 400 400"
        fill="none"
        aria-hidden
      >
        <circle cx="200" cy="200" r="160" stroke="white" strokeWidth="1" />
        <circle cx="200" cy="200" r="120" stroke="white" strokeWidth="1" />
        <circle cx="200" cy="200" r="80" stroke="white" strokeWidth="1" />
      </svg>

      <DisplayCrop>{HERO_CROP}</DisplayCrop>

      <div className="relative z-[1] mx-auto w-full max-w-4xl">
        <div
          className="mb-6 h-px w-full bg-[var(--rule-on-signal)]"
          aria-hidden
        />
        <div data-reveal>
          <SectionLabel tone="on-signal">{HERO_LABEL}</SectionLabel>
        </div>
        <h1
          data-reveal
          className="display-title mt-4 max-w-4xl text-paper"
        >
          {HERO_H1_LINES[0]}
          <br />
          {HERO_H1_LINES[1]}
        </h1>
        <div
          className="mt-6 h-px w-full bg-[var(--rule-on-signal)]"
          aria-hidden
        />
        <p
          data-reveal
          className="mx-auto mt-6 max-w-xl text-base leading-relaxed text-paper/95 md:text-lg"
        >
          {PRODUCT_ONE_LINER}
        </p>
        <div
          data-reveal
          className="mt-10 flex flex-wrap items-center justify-center gap-3"
        >
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center justify-center rounded-full border border-white/25 bg-charcoal px-6 py-3 text-sm font-bold text-paper transition-opacity hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
            data-cta="github-hero"
            data-github-url={GITHUB_URL}
            onClick={() => track("cta_github", { where: "hero" })}
          >
            {CTA_GET_ROUTISM}
          </a>
          <SectionLink
            id="demo"
            className="inline-flex items-center justify-center rounded-full border border-white/30 px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
          >
            {CTA_SEE_INSTALL}
          </SectionLink>
        </div>
        <p
          data-reveal
          className="mono mt-8 text-[10px] text-white/85 md:text-xs"
        >
          {heroMetaLine(INSTALL_COMMAND, MODEL_ID)}
        </p>
      </div>
    </section>
  );
}
