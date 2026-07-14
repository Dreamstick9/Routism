import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Routism — Multi-model orchestration for coding agents",
  description:
    "Self-hosted, OpenAI-compatible multi-model orchestration. Conduct many models. One API. MIT.",
  metadataBase: new URL("https://github.com/Dreamstick9/Routism"),
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
    <html lang="en" className="h-full">
      <body className="grain min-h-full antialiased">{children}</body>
    </html>
  );
}
