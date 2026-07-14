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
  const toneClass =
    tone === "on-light"
      ? "text-ink/55"
      : tone === "on-signal"
        ? "text-white/70"
        : "text-fog-dim";

  return (
    <p
      className={`text-[11px] font-medium uppercase tracking-[0.28em] ${toneClass} ${className}`}
    >
      {children}
    </p>
  );
}
