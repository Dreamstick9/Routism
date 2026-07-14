"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import {
  GITHUB_URL,
  SECTIONS,
  sectionHref,
} from "@/lib/product-facts";
import { scrollToSection } from "@/lib/scroll-map";
import {
  getScroller,
  resolveActiveSection,
  subscribeScroll,
} from "@/lib/scroll-controller";
import { track } from "@/lib/analytics";

const FOCUSABLE =
  'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])';

function isVisible(el: HTMLElement): boolean {
  // Prefer checkVisibility when available; avoid offsetParent fragility
  if (typeof el.checkVisibility === "function") {
    return el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true });
  }
  const style = window.getComputedStyle(el);
  return style.visibility !== "hidden" && style.display !== "none";
}

export default function Nav() {
  const [active, setActive] = useState<string>("world");
  const [open, setOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const sheetRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const sheetId = useId();

  useEffect(() => {
    const ids = SECTIONS.map((s) => s.id);
    const update = () => {
      setActive(resolveActiveSection(ids));
    };
    update();
    return subscribeScroll(update);
  }, []);

  const closeMenu = useCallback(() => {
    setOpen(false);
    // Return focus to menu button after close
    requestAnimationFrame(() => menuButtonRef.current?.focus());
  }, []);

  function go(id: string) {
    scrollToSection(id);
    track("nav_section", { id });
    // Restore focus to menu button only when the sheet was open
    if (open) closeMenu();
  }

  // Escape closes mobile sheet
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeMenu();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, closeMenu]);

  // Focus trap (document-level) + initial focus when sheet opens
  useEffect(() => {
    if (!open || !sheetRef.current) return;
    const sheet = sheetRef.current;
    const focusables = () =>
      Array.from(sheet.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => !el.hasAttribute("disabled") && isVisible(el),
      );

    const list = focusables();
    list[0]?.focus();

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const items = focusables();
      if (!items.length) {
        e.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const activeEl = document.activeElement as HTMLElement | null;
      const inside = activeEl ? sheet.contains(activeEl) : false;

      if (e.shiftKey) {
        if (!inside || activeEl === first) {
          e.preventDefault();
          last.focus();
        }
      } else if (!inside || activeEl === last) {
        e.preventDefault();
        first.focus();
      }
    };

    // Document-level so Tab cannot escape into header/page chrome
    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [open]);

  // inert page content behind the dialog; document Tab trap keeps focus in sheet
  useEffect(() => {
    if (!open) return;
    const main = document.getElementById("main");
    const footer = document.querySelector("footer");
    const topRow = barRef.current?.querySelector<HTMLElement>(
      "[data-nav-chrome]",
    );
    main?.setAttribute("inert", "");
    footer?.setAttribute("inert", "");
    // Inert logo / desktop nav / external CTA so only the dialog is interactive
    topRow?.setAttribute("inert", "");
    return () => {
      main?.removeAttribute("inert");
      footer?.removeAttribute("inert");
      topRow?.removeAttribute("inert");
    };
  }, [open]);

  // Body + Lenis scroll lock while sheet open
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const s = getScroller();
    s?.stop();
    return () => {
      document.body.style.overflow = prev;
      s?.start();
    };
  }, [open]);

  const pillFocus =
    "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring,#1A1A1A)]";

  return (
    <header
      ref={barRef}
      className="fixed top-0 left-0 right-0 z-40 px-3 pt-3 md:px-6 md:pt-4"
    >
      <div
        data-nav-chrome
        className="mx-auto flex max-w-6xl items-center justify-between gap-2"
      >
        {/* Logo pill */}
        <a
          href="#world"
          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[var(--paper,#FFFFFF)] text-sm font-bold text-[var(--ink,#1A1A1A)] shadow-sm ${pillFocus}`}
          aria-label="Routism home"
          onClick={(e) => {
            e.preventDefault();
            go("world");
          }}
        >
          R
        </a>

        {/* Center section pill (desktop) */}
        <nav
          className="hidden items-center gap-0.5 rounded-full bg-[var(--cream,#F5F0E8)] px-1.5 py-1.5 text-[13px] text-[var(--ink,#1A1A1A)] shadow-sm md:flex"
          aria-label="Primary"
        >
          {SECTIONS.map((s) => (
            <a
              key={s.id}
              href={sectionHref(s.id)}
              className={`rounded-full px-3 py-1.5 transition-colors ${pillFocus} ${
                active === s.id
                  ? "bg-[rgba(26,26,26,0.08)] font-semibold text-[var(--ink,#1A1A1A)]"
                  : "font-medium text-[var(--ink,#1A1A1A)]/70 hover:text-[var(--ink,#1A1A1A)]"
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
          {/* Dark CTA */}
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            className={`inline-flex items-center justify-center rounded-full bg-[var(--charcoal,#1A1A1A)] px-4 py-2 text-xs font-semibold text-[var(--paper,#FFFFFF)] shadow-sm transition-opacity hover:opacity-90 md:text-sm ${pillFocus}`}
            data-cta="github-nav"
            data-github-url={GITHUB_URL}
            onClick={() => track("cta_github", { where: "nav" })}
          >
            Get Routism
          </a>

          <button
            ref={menuButtonRef}
            type="button"
            className={`inline-flex h-10 items-center justify-center rounded-full bg-[var(--paper,#FFFFFF)] px-3 text-xs font-semibold text-[var(--ink,#1A1A1A)] shadow-sm md:hidden ${pillFocus}`}
            aria-expanded={open}
            aria-controls={sheetId}
            aria-haspopup="dialog"
            onClick={() => {
              if (open) closeMenu();
              else setOpen(true);
            }}
          >
            {open ? "Close" : "Menu"}
          </button>
        </div>
      </div>

      {/* Mobile sheet + backdrop */}
      {open && (
        <>
          <button
            type="button"
            tabIndex={-1}
            aria-label="Close menu"
            className="fixed inset-0 z-30 bg-black/40 md:hidden"
            onClick={closeMenu}
          />
          <div
            ref={sheetRef}
            id={sheetId}
            role="dialog"
            aria-modal="true"
            aria-label="Primary"
            className="relative z-40 mx-auto mt-3 max-w-6xl rounded-2xl bg-[var(--cream,#F5F0E8)] p-4 shadow-lg md:hidden"
          >
            <div className="mb-2 flex items-center justify-end">
              <button
                type="button"
                className={`rounded-full px-3 py-1.5 text-xs font-semibold text-[var(--ink,#1A1A1A)] ${pillFocus}`}
                onClick={closeMenu}
              >
                Close
              </button>
            </div>
            <nav aria-label="Mobile">
              <ul className="flex flex-col gap-1">
                {SECTIONS.map((s) => (
                  <li key={s.id}>
                    <a
                      href={sectionHref(s.id)}
                      className={`block rounded-xl px-3 py-2.5 text-sm ${pillFocus} ${
                        active === s.id
                          ? "bg-[rgba(26,26,26,0.08)] font-semibold text-[var(--ink,#1A1A1A)]"
                          : "font-medium text-[var(--ink,#1A1A1A)]/80"
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
          </div>
        </>
      )}
    </header>
  );
}
