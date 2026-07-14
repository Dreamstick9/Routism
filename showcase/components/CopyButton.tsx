"use client";

import { useState } from "react";
import { track } from "@/lib/analytics";

export default function CopyButton({
  text,
  label = "Copy",
  event = "copy",
  variant = "on-dark",
}: {
  text: string;
  label?: string;
  event?: string;
  /** Flat editorial styling for dark or cream fields */
  variant?: "on-dark" | "on-light";
}) {
  const [done, setDone] = useState(false);

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      track(event, { len: String(text.length) });
      setTimeout(() => setDone(false), 1600);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "absolute";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      setDone(true);
      track(event, { fallback: "1" });
      setTimeout(() => setDone(false), 1600);
    }
  }

  const base =
    "inline-flex items-center justify-center gap-2 rounded-full px-4 py-2 text-xs font-bold transition-colors";
  const styles =
    variant === "on-light"
      ? "border border-ink/20 bg-transparent text-ink hover:bg-ink hover:text-paper focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
      : "border border-white/20 bg-transparent text-fog hover:border-white/40 hover:bg-white/6 hover:text-paper focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white";

  return (
    <button
      type="button"
      onClick={onCopy}
      data-copy-payload={text}
      aria-label={done ? "Copied" : label}
      className={`${base} ${styles}`}
    >
      {done ? "Copied" : label}
    </button>
  );
}
