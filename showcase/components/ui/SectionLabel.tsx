import type { ReactNode } from "react";

type SectionLabelProps = {
  children: ReactNode;
  className?: string;
  /** ink on cream fields; paper/fog on dark/signal */
  tone?: "on-dark" | "on-light" | "on-signal";
};

export default function SectionLabel({
  children,
  className = "",
  tone = "on-dark",
}: SectionLabelProps) {
  /* Prefer ≥4.5:1 on cream/signal for 11px tracked labels (WCAG AA). */
  const toneClass =
    tone === "on-light"
      ? "text-ink/70"
      : tone === "on-signal"
        ? "text-white/90"
        : "text-fog-dim";

  return (
    <p
      className={`text-[11px] font-medium uppercase tracking-[0.28em] ${toneClass} ${className}`}
    >
      {children}
    </p>
  );
}
