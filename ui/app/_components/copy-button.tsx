"use client";

import { useState } from "react";

// Copy-to-clipboard button with transient "copied" feedback.
export default function CopyButton({
  value,
  label = "copy",
}: {
  value: string;
  label?: string;
}) {
  const [copied, setCopied] = useState(false);

  async function onCopy() {
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
      } else {
        const ta = document.createElement("textarea");
        ta.value = value;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      // best-effort
    }
  }

  return (
    <button
      type="button"
      onClick={onCopy}
      className="rounded-md border border-[var(--border)] bg-[var(--background-elevated)] px-1.5 py-0.5 text-[0.65rem] text-[var(--muted)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--foreground)]"
      title={`Copy "${value}"`}
    >
      {copied ? "copied" : label}
    </button>
  );
}
