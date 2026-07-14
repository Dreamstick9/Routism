"use client";

import type { MouseEvent, ReactNode } from "react";
import { sectionHref } from "@/lib/product-facts";
import { scrollToSection } from "@/lib/scroll-map";

type SectionLinkProps = {
  id: string;
  children: ReactNode;
  className?: string;
  onNavigate?: () => void;
};

/**
 * In-page section link that uses the Lenis-aware scroll controller
 * (nav offset) instead of native hash jumps.
 */
export default function SectionLink({
  id,
  children,
  className,
  onNavigate,
}: SectionLinkProps) {
  function onClick(e: MouseEvent<HTMLAnchorElement>) {
    e.preventDefault();
    scrollToSection(id);
    onNavigate?.();
  }

  return (
    <a href={sectionHref(id)} className={className} onClick={onClick}>
      {children}
    </a>
  );
}
