"use client";

import { useEffect } from "react";
import Lenis from "lenis";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { setScroller, scrollToSection } from "@/lib/scroll-controller";

gsap.registerPlugin(ScrollTrigger);

export default function SmoothScroll({
  children,
}: {
  children: React.ReactNode;
}) {
  useEffect(() => {
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

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

    const lenis = new Lenis({
      duration: 1.15,
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
          typeof target === "string"
            ? target
            : (target as HTMLElement);
        lenis.scrollTo(el, {
          offset: opts?.offset ?? -72,
          immediate: opts?.immediate ?? false,
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
    });

    const ticker = (time: number) => {
      lenis.raf(time * 1000);
    };
    gsap.ticker.add(ticker);
    gsap.ticker.lagSmoothing(0);

    const ctx = gsap.context(() => {
      gsap.utils.toArray<HTMLElement>("[data-chapter]").forEach((el) => {
        const targets = el.querySelectorAll("[data-reveal]");
        if (!targets.length) return;
        gsap.fromTo(
          targets,
          { y: 32, opacity: 0 },
          {
            y: 0,
            opacity: 1,
            duration: 0.85,
            stagger: 0.06,
            ease: "power3.out",
            immediateRender: false,
            scrollTrigger: {
              trigger: el,
              start: "top 80%",
              toggleActions: "play none none none",
              once: true,
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
            { y: 24, opacity: 0 },
            {
              y: 0,
              opacity: 1,
              duration: 0.9,
              stagger: 0.08,
              ease: "power3.out",
              delay: 0.1,
            },
          );
        }
      }
    });

    ScrollTrigger.refresh();

    // Hash deep-link after refresh
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
