import type { CSSProperties } from "react";

type PosterCardProps = {
  label: string;
  className?: string;
  /** Flat accent strip color token name */
  accent?: "lime" | "green" | "pink" | "blue" | "signal";
  style?: CSSProperties;
};

const ACCENT: Record<NonNullable<PosterCardProps["accent"]>, string> = {
  lime: "bg-accent-lime",
  green: "bg-accent-green",
  pink: "bg-accent-pink",
  blue: "bg-accent-blue",
  signal: "bg-signal",
};

export default function PosterCard({
  label,
  className = "",
  accent = "lime",
  style,
}: PosterCardProps) {
  return (
    <div
      className={`relative flex aspect-[3/4] min-h-[10rem] flex-col justify-end overflow-hidden rounded-sm bg-charcoal-soft p-4 shadow-[0_12px_40px_rgba(0,0,0,0.35)] ${className}`}
      style={style}
    >
      <div
        className={`absolute inset-x-0 top-0 h-1.5 ${ACCENT[accent]}`}
        aria-hidden
      />
      <span className="text-lg font-bold tracking-tight text-paper md:text-xl">
        {label}
      </span>
    </div>
  );
}
