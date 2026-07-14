"use client";

import { useEffect } from "react";
import Lenis from "lenis";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { setScroller, scrollToSection } from "@/lib/scroll-controller";
import {
  MOTION,
  canRunDesktopMotion,
  isDebugMotion,
  prefersReducedMotion,
} from "@/lib/motion-spec";

gsap.registerPlugin(ScrollTrigger);

export default function SmoothScroll({
  children,
}: {
  children: React.ReactNode;
}) {
  useEffect(() => {
    const reduce = prefersReducedMotion();

    if (reduce) {
      document.querySelectorAll<HTMLElement>("[data-reveal]").forEach((el) => {
        el.style.opacity = "1";
        el.style.transform = "none";
      });
      // Still handle hash without Lenis
      const hash = window.location.hash.replace("#", "");
      if (hash) {
        requestAnimationFrame(() => scrollToSection(hash));
      }
      return;
    }

    const debug = isDebugMotion();

    const lenis = new Lenis({
      duration: MOTION.lenisDuration,
      smoothWheel: true,
    });

    const scrollListeners = new Set<(y: number) => void>();

    lenis.on("scroll", (e: { scroll: number }) => {
      ScrollTrigger.update();
      for (const cb of scrollListeners) {
        cb(e.scroll);
      }
    });

    setScroller({
      scrollTo: (target, opts) => {
        const el =
          typeof target === "string" ? target : (target as HTMLElement);
        lenis.scrollTo(el, {
          offset: opts?.offset ?? MOTION.navOffset,
          immediate: opts?.immediate ?? false,
          // Allow programmatic nav while stop()'d (e.g. mobile menu open)
          force: opts?.force ?? false,
        });
      },
      onScroll: (cb) => {
        scrollListeners.add(cb);
        return () => {
          scrollListeners.delete(cb);
        };
      },
      refresh: () => {
        ScrollTrigger.refresh();
      },
      stop: () => {
        lenis.stop();
      },
      start: () => {
        lenis.start();
      },
    });

    const ticker = (time: number) => {
      lenis.raf(time * 1000);
    };
    gsap.ticker.add(ticker);
    gsap.ticker.lagSmoothing(0);

    const ctx = gsap.context(() => {
      const { reveal, heroReveal, parallax, tiers, glyphPin, fan, orbit } =
        MOTION;
      const desktop = canRunDesktopMotion();

      // Chapter fade-ups (MVP)
      gsap.utils.toArray<HTMLElement>("[data-chapter]").forEach((el) => {
        const targets = el.querySelectorAll("[data-reveal]");
        if (!targets.length) return;
        gsap.fromTo(
          targets,
          { y: reveal.y, opacity: 0 },
          {
            y: 0,
            opacity: 1,
            duration: reveal.duration,
            stagger: reveal.stagger,
            ease: reveal.ease,
            immediateRender: false,
            scrollTrigger: {
              trigger: el,
              start: "top 80%",
              toggleActions: "play none none none",
              once: true,
              markers: debug,
            },
          },
        );
      });

      // Hero is already in view — play immediately
      const hero = document.getElementById("world");
      if (hero) {
        const heroTargets = hero.querySelectorAll("[data-reveal]");
        if (heroTargets.length) {
          gsap.fromTo(
            heroTargets,
            { y: heroReveal.y, opacity: 0 },
            {
              y: 0,
              opacity: 1,
              duration: heroReveal.duration,
              stagger: heroReveal.stagger,
              ease: heroReveal.ease,
              delay: heroReveal.delay,
            },
          );
        }
      }

      // PR-4a: parallax plates — desktop only, reduced-motion already gated above
      if (tiers.parallax && desktop) {
        const intensity = parallax.yPercent;
        gsap.utils
          .toArray<HTMLElement>('[data-motion="parallax"]')
          .forEach((el) => {
            const trigger =
              el.closest<HTMLElement>("[data-chapter]") ??
              el.closest<HTMLElement>("section") ??
              el;
            gsap.fromTo(
              el,
              { yPercent: -intensity },
              {
                yPercent: intensity,
                ease: "none",
                immediateRender: false,
                scrollTrigger: {
                  trigger,
                  start: "top bottom",
                  end: "bottom top",
                  scrub: true,
                  markers: debug,
                },
              },
            );
          });
      }

      // PR-4b advanced — all skipped under reduced-motion (early return above)
      if (tiers.advanced) {
        // --- glyph-scrub (TypeSplitMorph): pin desktop-only ---
        if (desktop) {
          gsap.utils
            .toArray<HTMLElement>('[data-motion="glyph-scrub"]')
            .forEach((section) => {
              const glyphs =
                section.querySelectorAll<HTMLElement>("[data-glyph]");
              if (!glyphs.length) return;

              const tl = gsap.timeline({
                defaults: { ease: "none" },
                scrollTrigger: {
                  trigger: section,
                  start: "top top",
                  end: glyphPin.end,
                  pin: true,
                  scrub: true,
                  anticipatePin: 1,
                  markers: debug,
                },
              });

              const amp = glyphPin.xPercent;
              glyphs.forEach((glyph, i) => {
                // ENGINE drifts left; WORKERS drifts right (opposite scrub)
                const from = i % 2 === 0 ? amp * 0.4 : -amp * 0.4;
                const to = i % 2 === 0 ? -amp : amp;
                tl.fromTo(glyph, { xPercent: from }, { xPercent: to }, 0);
              });
            });
        }

        // --- fan (PaperStack): stack → −6° / 0° / 6° on enter ---
        gsap.utils
          .toArray<HTMLElement>('[data-motion="fan"]')
          .forEach((root) => {
            const cards =
              root.querySelectorAll<HTMLElement>("[data-fan-card]");
            if (!cards.length) return;

            // Collapse to stack immediately (markup carries pre-fan for reduced-motion)
            gsap.set(cards, { rotate: 0, x: 0, y: 0 });

            gsap.to(cards, {
              rotate: (i: number) => (i - 1) * fan.angleDeg,
              x: (i: number) => (i - 1) * fan.xPx,
              y: (i: number) => i * fan.yPx,
              duration: fan.duration,
              ease: fan.ease,
              stagger: 0.08,
              scrollTrigger: {
                trigger: root,
                start: fan.start,
                toggleActions: "play none none none",
                once: true,
                markers: debug,
              },
            });
          });

        // --- orbit (EcosystemOrbit): scrub rotateY/Z ±8–18° ---
        gsap.utils
          .toArray<HTMLElement>('[data-motion="orbit"]')
          .forEach((section) => {
            const stage =
              section.querySelector<HTMLElement>("[data-orbit-stage]") ??
              section;
            const cards =
              section.querySelectorAll<HTMLElement>("[data-orbit-card]");
            if (!cards.length) return;

            gsap.set(stage, {
              perspective: orbit.perspectivePx,
              transformStyle: "preserve-3d",
            });

            cards.forEach((card, i) => {
              const sign = i % 2 === 0 ? 1 : -1;
              const yAmp = orbit.rotateY * sign;
              const zAmp =
                orbit.rotateZ * ((i - (cards.length - 1) / 2) / cards.length);

              gsap.fromTo(
                card,
                {
                  rotateY: -yAmp,
                  rotateZ: -zAmp,
                  transformPerspective: orbit.perspectivePx,
                },
                {
                  rotateY: yAmp,
                  rotateZ: zAmp,
                  ease: "none",
                  immediateRender: false,
                  scrollTrigger: {
                    trigger: section,
                    start: "top bottom",
                    end: "bottom top",
                    scrub: true,
                    markers: debug,
                  },
                },
              );
            });
          });

        // --- marquee (VariantsMarquee): enable CSS infinite track ---
        gsap.utils
          .toArray<HTMLElement>('[data-motion="marquee"]')
          .forEach((el) => {
            el.classList.add("is-marquee-active");
            el.style.setProperty(
              "--marquee-seconds",
              String(MOTION.marqueeSeconds),
            );
          });
      }
    });

    // Mount order: Lenis + registrations → refresh → hash deep-link
    ScrollTrigger.refresh();

    const hash = window.location.hash.replace("#", "");
    if (hash) {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => scrollToSection(hash));
      });
    }

    const onLoad = () => ScrollTrigger.refresh();
    window.addEventListener("load", onLoad);

    let resizeTimer: ReturnType<typeof setTimeout> | undefined;
    const onResize = () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => ScrollTrigger.refresh(), 150);
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("load", onLoad);
      window.removeEventListener("resize", onResize);
      clearTimeout(resizeTimer);
      document
        .querySelectorAll<HTMLElement>('[data-motion="marquee"].is-marquee-active')
        .forEach((el) => {
          el.classList.remove("is-marquee-active");
          el.style.removeProperty("--marquee-seconds");
        });
      ctx.revert();
      gsap.ticker.remove(ticker);
      setScroller(null);
      lenis.destroy();
      ScrollTrigger.getAll().forEach((t) => t.kill());
    };
  }, []);

  return <>{children}</>;
}
