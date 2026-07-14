/** Lightweight event hook — no third-party required. */
export function track(event: string, detail?: Record<string, string>): void {
  if (typeof window === "undefined") return;
  try {
    window.dispatchEvent(
      new CustomEvent("routism-showcase", { detail: { event, ...detail } }),
    );
    // Optional Plausible / gtag if present
    const w = window as unknown as {
      plausible?: (e: string, o?: { props?: Record<string, string> }) => void;
    };
    w.plausible?.(event, detail ? { props: detail } : undefined);
  } catch {
    /* ignore */
  }
}
