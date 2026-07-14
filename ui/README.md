# Routism UI

The Provider Hub dashboard for [Routism](https://github.com/your-org/routism) — a
Fugu-Ultra-style multi-LLM orchestrator. This is a thin Next.js client over the
Routism backend (FastAPI on `:8000`); it makes no backend architecture changes.

## Stack
- Next.js 16 (App Router) + TypeScript
- Tailwind CSS v4
- Talks to the Routism backend at `http://localhost:8000` (override with
  `NEXT_PUBLIC_ROUTISM_API`).

## Running
Start the backend (separate terminal):
```bash
cd .
python3 -m routism.run   # FastAPI on :8000
```
Then start the UI:
```bash
npm install
npm run dev      # http://localhost:3000
# or
npm run build && npm start
```

## Pages
- `/` and `/providers` — the Providers panel. Connect up to five OpenAI-compatible
  LLM endpoints (local or cloud), see health, test connections, remove them. The
  footer shows the live pool size (`N/5 providers connected`).
- `/plan` — describe a task; the orchestrator returns a plan rendered as step
  cards (one per worker), plus the final synthesized answer.

## Backend contract
The UI calls these backend endpoints (see `lib/api.ts`):
- `GET  /v1/management/pool`
- `POST /v1/management/pool` (returns 400 `pool full` at 5)
- `DELETE /v1/management/pool/{id}`
- `GET  /v1/management/health/{id}`
- `POST /api/plan`

The backend must run with CORS enabled for `http://localhost:3000` (added in P4.A/C).
See the main Routism repo for backend setup (`routism.yaml`, provider pool config).

## Try it
1. Start the backend and the UI (commands above).
2. Open http://localhost:3000, go to **Providers**, add up to five LLM endpoints.
3. Go to **Plan**, ask a question, and watch the orchestrator decompose it into
   visible step cards.

Full screen-flow demo (ASCII frames + isolation/persistence notes): [`docs/demo.md`](./docs/demo.md).
