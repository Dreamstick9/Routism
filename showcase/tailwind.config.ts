import type { Config } from "tailwindcss";

export default {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        void: "var(--void)",
        charcoal: "var(--charcoal)",
        "charcoal-soft": "var(--charcoal-soft)",
        signal: "var(--signal)",
        "signal-hot": "var(--signal-hot)",
        cream: "var(--cream)",
        "cream-deep": "var(--cream-deep)",
        ink: "var(--ink)",
        paper: "var(--paper)",
        fog: "var(--fog)",
        "fog-dim": "var(--fog-dim)",
        lime: "var(--accent-lime)",
        "accent-green": "var(--accent-green)",
        "accent-pink": "var(--accent-pink)",
        "accent-blue": "var(--accent-blue)",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SF Mono", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
