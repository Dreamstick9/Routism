# Routism showcase (marketing site)

Editorial product showcase for **Routism** — not the product dashboard (`../ui`).

Visual system targets a Neue Montreal–inspired editorial language: full-bleed
signal red / void / cream fields, flat accents, Inter type. CSS variables in
`app/globals.css` are the color source of truth; Tailwind mirrors semantic
tokens (`bg-signal`, `text-ink`, `bg-cream`, etc.).

**No neon.** Do not reintroduce cyan `#2de2e6`, magenta `#ff2a6d`, R3F/Three
heroes, glass glow CTAs, or Pangram/Framer hotlinked fonts/media.

## Run locally

```bash
cd showcase
npm ci
cp .env.example .env.local   # optional; see env below
npm run dev                  # http://localhost:3100
```

## Production

```bash
npm run build
npm start                    # http://localhost:3100
```

### Environment

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_SHOWCASE_URL` | Absolute site URL for `metadataBase` / Open Graph. |

- Documented in `.env.example` as `NEXT_PUBLIC_SHOWCASE_URL=`.
- **Fallback when unset:** `http://localhost:3100` (see `app/layout.tsx`).
- Set this at deploy once the real public domain is known.
- **Do not invent a production domain** in source.

## Fact-check tests

Product claims (install command, model id, GitHub URL, section anchors) live in
`lib/product-facts.ts`. Presentational copy lives in `lib/content.ts`.

```bash
npm test
npm run typecheck
npm run build
```

## Lighthouse (performance & a11y)

Targets (desktop, local production build):

| Category | Floor |
|---|---|
| Performance | **≥ 85** |
| Accessibility | **≥ 95** |

How to measure (scores are **not** committed; re-run after visual changes):

```bash
cd showcase
npm run build
npm start   # keep running on http://localhost:3100

# Chrome DevTools → Lighthouse → Desktop → Performance + Accessibility
# or CLI (if installed):
npx lighthouse http://localhost:3100 \
  --only-categories=performance,accessibility \
  --preset=desktop \
  --view
```

Notes for operators:

- Hero is text/SVG (no video / no Three.js) so LCP should stay text-led.
- Inter is limited to **4 weights** via `next/font` with `display: swap`.
- Prefer reduced-motion on when auditing motion-related jank.
- Paste scores in the PR description when available; do not invent scores.

## Frame acceptance checklist

Layout/motion reference only (do **not** commit scraped frames or Pangram
CDN assets into `public/`). Field colors must match CSS tokens.

| Frame | Required UI | Pass criteria |
|---|---|---|
| **001** | Red full-bleed field; massive white multi-line H1; thin horizontal rules; pill nav + lettermark + dark CTA; optional crop word | Field is `--signal` (not cyan void); H1 from copy deck; **no** R3F canvas |
| **002** | Dark void; multiple tilted / grid poster cards; center space | ≥4 ecosystem posters with name-only labels; static grid OK (orbit polish optional) |
| **003** | Full-bleed architecture plate; centered display headline + body | `#split` shows **Engine ≠ Workers** + `ENGINE_VS_WORKERS`; no glass cards |
| **004** | Cream field; giant black letterforms; small corner labels | TypeSplitMorph present (static crop OK); labels **Conductor / Pool** (not foundry jargon) |
| **005** | Cream field; stacked colored paper cards; body around stack | PaperStack 3 cards **Plan / Execute / Merge**; lime / green / signal accents |
| **006–007** | Red footer; multi-column links; huge black wordmark; marquee strip of colored cards | FooterRed + **ROUTISM** wordmark; VariantsMarquee (static OK); GitHub/docs from `product-facts` |

**Rhythm (top → bottom):** red hero → black hook → plate/split → cream craft
modules → install → proof → download → red footer. Missing advanced motion is
OK if static compositions occupy the same slots.

**Visual QA:** 1440 desktop + 390 mobile; Chrome/Safari; `prefers-reduced-motion`.

## Launch greps (must be clean)

From `showcase/` (excluding design docs / node_modules):

```bash
rg -n '2de2e6|ff2a6d|HeroScene|@react-three|pangrampangram|from ["'\'']three["'\'']' \
  --glob '!node_modules/**' --glob '!*.md' .
```

Expect **no matches**. Also ensure `package.json` has no `three` / `@react-three/*`.

## Accessibility notes

- Skip link (`.skip-link`): paper fill + ink type + dual ring so it remains
  readable on the signal-red hero when focused.
- Focus rings: white on void/signal; dark (`--focus-ring-on-light`) on
  `.field-cream` / `.field-paper`.
- Mobile nav: dialog + focus trap + Escape + return focus to menu button.
- Dark charcoal CTAs on signal use a light border so the pill edge is visible.

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
`bg-accent-pink`, `bg-accent-blue`. Short alias `lime` → same as `accent-lime`.
Cream/paper sections should use class `field-cream` / `field-paper` so focus
rings switch to `--focus-ring-on-light`.

**Legacy aliases** (`--filament`, `--pulse`, `--acid`, `--border-glow`, `.glass`,
`.cta-primary`, `.card-proof`, etc.) remain for compatibility. Prefer new
semantic tokens in new components. Do not reintroduce neon hex values.

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
