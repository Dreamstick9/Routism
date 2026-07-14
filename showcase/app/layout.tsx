import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  weight: ["400", "500", "700", "800", "900"],
  display: "swap",
  variable: "--font-inter",
});

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
    <html lang="en" className={`h-full ${inter.variable}`}>
      <body className={`${inter.className} min-h-full antialiased`}>
        {children}
      </body>
    </html>
  );
}
