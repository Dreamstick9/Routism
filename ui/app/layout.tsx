import Link from "next/link";
import "./globals.css";
import Nav from "./nav";
import PoolChip from "./pool-chip";

export const metadata = {
  title: "Routism",
  description:
    "Self-hosted OpenAI-compatible multi-model orchestration for coding agents",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full">
      <body className="flex min-h-full flex-col antialiased">
        <header className="sticky top-0 z-20 border-b border-[var(--border)] bg-[color-mix(in_srgb,var(--background)_88%,transparent)] backdrop-blur-md">
          <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-5 py-3.5 sm:px-6">
            <Link href="/" className="group flex items-center gap-2.5">
              <span
                className="flex h-8 w-8 items-center justify-center rounded-xl bg-[var(--accent)] text-sm font-semibold text-[var(--accent-text)] shadow-[var(--shadow-sm)]"
                aria-hidden
              >
                R
              </span>
              <span
                className="text-[1.05rem] font-semibold tracking-tight text-[var(--foreground)]"
                style={{ fontFamily: "var(--font-display)" }}
              >
                Routism
              </span>
            </Link>
            <Nav />
          </div>
        </header>

        <main className="mx-auto w-full max-w-5xl flex-1 px-5 py-9 sm:px-6 sm:py-10">
          {children}
        </main>

        <footer className="border-t border-[var(--border)] bg-[color-mix(in_srgb,var(--card)_70%,transparent)]">
          <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-5 py-4 text-xs text-[var(--muted)] sm:px-6">
            <span>Routism · MIT · self-hosted orchestration API</span>
            <PoolChip />
          </div>
        </footer>
      </body>
    </html>
  );
}
