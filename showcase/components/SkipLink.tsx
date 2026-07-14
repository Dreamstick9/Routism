/** Accessible skip-to-main link with tokenized focus styles. */
export default function SkipLink() {
  return (
    <a
      href="#main"
      className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[60] focus:rounded-lg focus:bg-[var(--charcoal,#1A1A1A)] focus:px-4 focus:py-2 focus:text-[var(--paper,#FFFFFF)] focus:outline focus:outline-2 focus:outline-offset-2 focus:outline-[var(--focus-ring,#FFFFFF)]"
    >
      Skip to content
    </a>
  );
}
