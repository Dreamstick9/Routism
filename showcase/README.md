# Routism showcase (marketing site)

Editorial product showcase for **Routism** — not the product dashboard (`../ui`).

Visual system targets a Neue Montreal–inspired editorial language: full-bleed
signal red / void / cream fields, flat accents, Inter type. CSS variables in
`app/globals.css` are the color source of truth; Tailwind mirrors semantic
tokens (`bg-signal`, `text-ink`, `bg-cream`, etc.).

## Run locally

```bash
cd showcase
npm ci
npm run dev      # http://localhost:3100
```

## Production

```bash
npm run build
npm start        # http://localhost:3100
```

## Fact-check tests

Product claims (install command, model id, GitHub URL, section anchors) live in
`lib/product-facts.ts` and are unit-tested:

```bash
npm test
```

## Design tokens

Defined in `app/globals.css` (`:root`):

| Token | Role |
|---|---|
| `--void` / `--charcoal` / `--charcoal-soft` | Black fields & panels |
| `--signal` / `--signal-hot` | Red hero/footer & hot accents |
| `--cream` / `--cream-deep` / `--ink` / `--paper` | Paper sections & type |
| `--fog` / `--fog-dim` | Body / muted on dark |
| `--accent-lime` / `--accent-green` / `--accent-pink` / `--accent-blue` | Flat graphic accents |
| `--selection-*` / `--focus-ring*` | Selection & keyboard focus |

**Tailwind color mirrors:** prefer `bg-accent-lime`, `bg-accent-green`,
`bg-accent-pink`, `bg-accent-blue`. Short alias `lime` → same as `accent-lime`
(design-doc sample). Cream/paper sections should use class `field-cream` /
`field-paper` so focus rings switch to `--focus-ring-on-light`.

**Legacy aliases** (`--filament`, `--pulse`, `--acid`, `--border-glow`, `.glass`,
`.cta-primary`, `.card-proof`, etc.) remain so the current `page.tsx` stays
usable during the reskin. Prefer new semantic tokens in new components.

**Type:** Inter only via `next/font/google`, weights **400, 500, 700, 900**
(exactly four faces; performance budget ≤4). Prefer `font-medium` (500) or
`font-bold` (700) over `font-semibold` (600) so UI hits a real face. No
commercial foundry fonts; no Framer/Pangram font CDNs.

**Grain:** not on `body` by default; optional `.grain-editorial` only.

## Stack

- Next.js App Router
- Inter (next/font)
- GSAP ScrollTrigger + Lenis (scroll chapters)
- Tailwind CSS (semantic color mirrors of CSS variables)

Port **3100** avoids clashing with the product UI on **3000**.
