import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  /* ≤4 weights per performance budget; skip 600/800 — use 500 or 700 in UI */
  weight: ["400", "500", "700", "900"],
  display: "swap",
  variable: "--font-inter",
});

/* Production domain is set via NEXT_PUBLIC_SHOWCASE_URL when known — do not invent one. */
const showcaseUrl =
  process.env.NEXT_PUBLIC_SHOWCASE_URL || "http://localhost:3100";

export const metadata: Metadata = {
  title: "Routism — Multi-model orchestration for coding agents",
  description:
    "Self-hosted, OpenAI-compatible multi-model orchestration. Conduct many models. One API. MIT.",
  metadataBase: new URL(showcaseUrl),
  openGraph: {
    title: "Routism",
    description:
      "Self-hosted OpenAI-compatible multi-model orchestration for coding agents.",
    type: "website",
  },
  robots: { index: true, follow: true },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`h-full ${inter.variable}`}>
      <body className={`${inter.className} min-h-full antialiased`}>
        {children}
      </body>
    </html>
  );
}
