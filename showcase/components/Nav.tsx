"use client";

import { useEffect, useState } from "react";
import {
  GITHUB_URL,
  SECTIONS,
  sectionHref,
} from "@/lib/product-facts";
import { scrollToSection } from "@/lib/scroll-map";
import { track } from "@/lib/analytics";

export default function Nav() {
  const [active, setActive] = useState<string>("world");
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const ids = SECTIONS.map((s) => s.id);
    const onScroll = () => {
      setScrolled(window.scrollY > 40);
      let current = ids[0];
      for (const id of ids) {
        const el = document.getElementById(id);
        if (!el) continue;
        const top = el.getBoundingClientRect().top;
        if (top <= window.innerHeight * 0.35) current = id;
      }
      setActive(current);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  function go(id: string) {
    scrollToSection(id);
    setOpen(false);
    track("nav_section", { id });
  }

  return (
    <header
      className={`fixed top-0 left-0 right-0 z-40 transition-all ${
        scrolled || open ? "glass" : "bg-transparent"
      }`}
    >
      <div className="flex items-center justify-between px-4 py-3 md:px-8">
        <a
          href="#world"
          className="font-bold tracking-tight text-white"
          onClick={(e) => {
            e.preventDefault();
            go("world");
          }}
        >
          Routism
          <span className="filament-text">.</span>
        </a>

        <nav
          className="glass hidden items-center gap-1 rounded-full px-2 py-1.5 text-sm md:flex"
          aria-label="Primary"
        >
          {SECTIONS.map((s) => (
            <a
              key={s.id}
              href={sectionHref(s.id)}
              className={`rounded-full px-3 py-1.5 transition-colors ${
                active === s.id
                  ? "bg-[rgba(45,226,230,0.15)] text-[var(--filament)]"
                  : "text-[var(--fog-dim)] hover:text-white"
              }`}
              onClick={(e) => {
                e.preventDefault();
                go(s.id);
              }}
            >
              {s.label}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="cta-secondary !px-3 !py-1.5 text-xs md:!px-4 md:text-sm"
            data-cta="github-nav"
            data-github-url={GITHUB_URL}
            onClick={() => track("cta_github", { where: "nav" })}
          >
            GitHub
          </a>
          <button
            type="button"
            className="cta-secondary !px-3 !py-1.5 text-xs md:hidden"
            aria-expanded={open}
            aria-controls="mobile-nav"
            onClick={() => setOpen((v) => !v)}
          >
            {open ? "Close" : "Menu"}
          </button>
        </div>
      </div>

      {open && (
        <nav
          id="mobile-nav"
          className="border-t border-white/10 px-4 py-3 md:hidden"
          aria-label="Mobile"
        >
          <ul className="flex flex-col gap-1">
            {SECTIONS.map((s) => (
              <li key={s.id}>
                <a
                  href={sectionHref(s.id)}
                  className={`block rounded-lg px-3 py-2 text-sm ${
                    active === s.id
                      ? "bg-[rgba(45,226,230,0.12)] text-[var(--filament)]"
                      : "text-[var(--fog)]"
                  }`}
                  onClick={(e) => {
                    e.preventDefault();
                    go(s.id);
                  }}
                >
                  {s.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      )}
    </header>
  );
}
