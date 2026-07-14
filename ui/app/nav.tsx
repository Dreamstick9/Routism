"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Overview", match: (p: string) => p === "/" },
  { href: "/providers", label: "Providers", match: (p: string) => p.startsWith("/providers") },
  { href: "/keys", label: "API keys", match: (p: string) => p.startsWith("/keys") },
  {
    href: "/orchestration",
    label: "Orchestration",
    match: (p: string) => p.startsWith("/orchestration"),
  },
  { href: "/settings", label: "Settings", match: (p: string) => p.startsWith("/settings") },
] as const;

const LAB = [
  { href: "/plan", label: "Plan" },
  { href: "/metrics", label: "Metrics" },
  { href: "/benchmarks", label: "Benchmarks" },
] as const;

export default function Nav() {
  const pathname = usePathname() || "/";

  return (
    <div className="flex flex-wrap items-center gap-2">
      <nav className="flex flex-wrap items-center gap-1 text-sm">
        {LINKS.map((link) => {
          const active = link.match(pathname);
          return (
            <Link
              key={link.href}
              href={link.href}
              className={
                active
                  ? "rounded-[var(--radius-pill)] bg-[var(--accent-soft)] px-3 py-1.5 font-medium text-[var(--accent)]"
                  : "rounded-[var(--radius-pill)] px-3 py-1.5 text-[var(--muted)] transition-colors hover:bg-[var(--card)] hover:text-[var(--foreground)]"
              }
            >
              {link.label}
            </Link>
          );
        })}
      </nav>
      <details className="relative text-sm">
        <summary className="cursor-pointer list-none rounded-[var(--radius-pill)] px-3 py-1.5 text-[var(--muted)] hover:bg-[var(--card)]">
          Advanced ▾
        </summary>
        <div className="absolute right-0 z-30 mt-1 min-w-[10rem] rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--card)] py-1 shadow-[var(--shadow)]">
          {LAB.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="block px-3 py-1.5 text-[var(--muted)] hover:bg-[var(--accent-soft)] hover:text-[var(--accent)]"
            >
              {link.label}
            </Link>
          ))}
        </div>
      </details>
    </div>
  );
}
