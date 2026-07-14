import type { ReactNode } from "react";

type DisplayCropProps = {
  children: ReactNode;
  className?: string;
  /** CSS color for the crop word */
  colorClass?: string;
};

/**
 * Oversized display fragment that bleeds past the section edge (static MVP).
 */
export default function DisplayCrop({
  children,
  className = "",
  colorClass = "text-white/10",
}: DisplayCropProps) {
  return (
    <div
      className={`pointer-events-none absolute inset-x-0 bottom-0 overflow-hidden select-none ${className}`}
      aria-hidden
    >
      <p
        className={`translate-y-[35%] whitespace-nowrap text-center font-bold leading-none tracking-[-0.06em] ${colorClass}`}
        style={{ fontSize: "clamp(6rem, 22vw, 18rem)" }}
      >
        {children}
      </p>
    </div>
  );
}
