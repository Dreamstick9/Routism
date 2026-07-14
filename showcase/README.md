# Routism showcase (marketing site)

Lusion-inspired product showcase for **Routism** — not the product dashboard (`../ui`).

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

## Stack

- Next.js App Router
- React Three Fiber / Three.js (hero world)
- GSAP ScrollTrigger + Lenis (scroll chapters)
- Tailwind CSS

Port **3100** avoids clashing with the product UI on **3000**.
