"use client";

import { useState } from "react";
import { track } from "@/lib/analytics";

export default function CopyButton({
  text,
  label = "Copy",
  event = "copy",
}: {
  text: string;
  label?: string;
  event?: string;
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

  return (
    <button
      type="button"
      onClick={onCopy}
      data-copy-payload={text}
      aria-label={done ? "Copied" : label}
      className="cta-secondary !py-1.5 !px-3 text-xs"
    >
      {done ? "Copied" : label}
    </button>
  );
}
