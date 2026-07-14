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
      const { reveal, heroReveal, parallax, tiers } = MOTION;

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
      if (tiers.parallax && canRunDesktopMotion()) {
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
      ctx.revert();
      gsap.ticker.remove(ticker);
      setScroller(null);
      lenis.destroy();
      ScrollTrigger.getAll().forEach((t) => t.kill());
    };
  }, []);

  return <>{children}</>;
}
